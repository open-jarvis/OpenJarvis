//! Shell execution tool.

use crate::traits::BaseTool;
use openjarvis_core::{OpenJarvisError, ToolResult, ToolSpec};
use once_cell::sync::Lazy;
use serde_json::Value;
use std::collections::HashMap;
use std::io::{self, Read};
#[cfg(unix)]
use std::process::{Child, Command, Stdio};
#[cfg(all(windows, test))]
use std::process::Command;
use std::sync::atomic::{AtomicBool, Ordering};
use std::sync::{Arc, Mutex};
use std::thread;
use std::time::{Duration, Instant};

const DEFAULT_TIMEOUT_SECONDS: u64 = 30;
const MAX_TIMEOUT_SECONDS: u64 = 300;
const MAX_OUTPUT_BYTES: usize = 102_400;
const STDOUT_TRUNCATION_MARKER: &str = "\n[stdout truncated: combined capture limit reached]";
const STDERR_TRUNCATION_MARKER: &str = "\n[stderr truncated: combined capture limit reached]";
const MAX_CAPTURE_BYTES: usize = MAX_OUTPUT_BYTES
    - STDOUT_TRUNCATION_MARKER.len()
    - STDERR_TRUNCATION_MARKER.len();
const POLL_INTERVAL: Duration = Duration::from_millis(10);
#[cfg(unix)]
const TERMINATE_GRACE: Duration = Duration::from_millis(250);

static SPEC: Lazy<ToolSpec> = Lazy::new(|| ToolSpec {
    name: "shell_exec".into(),
    description: "Execute a shell command and return its output".into(),
    parameters: serde_json::json!({
        "type": "object",
        "properties": {
            "command": { "type": "string", "description": "Shell command to execute" },
            "cwd": { "type": "string", "description": "Working directory (optional)" },
            "timeout": { "type": "integer", "description": "Timeout in seconds (default 30, maximum 300)" },
        },
        "required": ["command"]
    }),
    category: "system".into(),
    cost_estimate: 0.0,
    latency_estimate: 0.0,
    requires_confirmation: true,
    timeout_seconds: DEFAULT_TIMEOUT_SECONDS as f64,
    required_capabilities: vec!["code:execute".into()],
    metadata: HashMap::new(),
});

/// Bounded process output and status returned by the shell tool.
#[derive(Debug)]
pub struct ShellExecOutput {
    pub content: String,
    pub success: bool,
    pub returncode: i32,
    pub timed_out: bool,
    pub stdout_truncated: bool,
    pub stderr_truncated: bool,
    pub timeout_used: u64,
}

pub struct ShellExecTool;

fn timeout_seconds(params: &Value) -> u64 {
    params["timeout"]
        .as_u64()
        .unwrap_or(DEFAULT_TIMEOUT_SECONDS)
        .clamp(1, MAX_TIMEOUT_SECONDS)
}

fn platform_environment() -> HashMap<std::ffi::OsString, std::ffi::OsString> {
    let mut allowed = vec!["PATH", "HOME", "USER", "LANG", "TERM"];
    #[cfg(windows)]
    allowed.extend([
        "SystemRoot", "SystemDrive", "COMSPEC", "PATHEXT", "TEMP", "TMP",
        "USERPROFILE", "LOCALAPPDATA", "APPDATA",
    ]);

    let mut env = HashMap::new();
    for key in allowed {
        if let Some(value) = std::env::var_os(key) {
            env.insert(key.into(), value);
        }
    }
    env
}

#[cfg(unix)]
fn bounded_reader<R: Read>(
    mut reader: R,
    remaining_budget: Arc<Mutex<usize>>,
    output_limited: Arc<AtomicBool>,
) -> (Vec<u8>, bool) {
    let mut captured = Vec::with_capacity(MAX_OUTPUT_BYTES.min(8192));
    let mut truncated = false;
    let mut buffer = [0_u8; 8192];
    loop {
        if output_limited.load(Ordering::Acquire) {
            // One final bounded read tells us whether this stream also had
            // uncaptured bytes. The supervisor is terminating the tree now,
            // so this read cannot remain blocked on an active writer.
            let read = match reader.read(&mut buffer) {
                Ok(read) => read,
                Err(error) if error.kind() == io::ErrorKind::Interrupted => continue,
                Err(_) => break,
            };
            truncated |= read > 0;
            break;
        }
        let read = match reader.read(&mut buffer) {
            Ok(read) => read,
            Err(error) if error.kind() == io::ErrorKind::Interrupted => continue,
            Err(_) => break,
        };
        if read == 0 {
            break;
        }
        let keep = {
            let mut remaining = remaining_budget.lock().unwrap_or_else(|e| e.into_inner());
            let keep = (*remaining).min(read);
            *remaining -= keep;
            keep
        };
        captured.extend_from_slice(&buffer[..keep]);
        truncated |= keep < read;
        if keep < read {
            output_limited.store(true, Ordering::Release);
            break;
        }
    }
    (captured, truncated)
}

#[cfg(windows)]
fn bounded_reader_windows(
    mut reader: std::fs::File,
    remaining_budget: Arc<Mutex<usize>>,
    output_exceeded: Arc<AtomicBool>,
    readers_stop: Arc<AtomicBool>,
) -> (Vec<u8>, bool) {
    use std::os::windows::io::AsRawHandle;

    let mut captured = Vec::with_capacity(MAX_OUTPUT_BYTES.min(8192));
    let mut truncated = false;
    let mut buffer = [0_u8; 8192];
    loop {
        let mut available = 0u32;
        // SAFETY: PeekNamedPipe inspects this owned pipe without consuming bytes.
        let peeked = unsafe {
            windows_native::peek_available(reader.as_raw_handle().cast(), &mut available)
        };
        if !peeked {
            break;
        }
        if available == 0 {
            if output_exceeded.load(Ordering::Acquire)
                || readers_stop.load(Ordering::Acquire)
            {
                break;
            }
            thread::sleep(POLL_INTERVAL);
            continue;
        }
        if output_exceeded.load(Ordering::Acquire) {
            // This stream has uncaptured bytes queued after the shared budget
            // was exhausted by the other reader.
            truncated = true;
            break;
        }

        let requested = available.min(buffer.len() as u32) as usize;
        let read = match reader.read(&mut buffer[..requested]) {
            Ok(read) => read,
            Err(error) if error.kind() == io::ErrorKind::Interrupted => continue,
            Err(_) => break,
        };
        if read == 0 {
            break;
        }
        let keep = {
            let mut remaining = remaining_budget.lock().unwrap_or_else(|e| e.into_inner());
            let keep = (*remaining).min(read);
            *remaining -= keep;
            keep
        };
        captured.extend_from_slice(&buffer[..keep]);
        if keep < read {
            truncated = true;
            output_exceeded.store(true, Ordering::Release);
            break;
        }
    }
    (captured, truncated)
}

#[cfg(windows)]
mod windows_native {
    use std::ffi::{c_void, OsStr};
    use std::fs::File;
    use std::io;
    use std::mem::{size_of, zeroed};
    use std::os::windows::ffi::OsStrExt;
    use std::os::windows::io::FromRawHandle;
    use std::path::Path;
    use std::thread;
    use std::time::{Duration, Instant};

    pub(super) type Handle = *mut c_void;

    #[repr(C)]
    #[derive(Default)]
    struct BasicLimitInformation {
        per_process_user_time_limit: i64,
        per_job_user_time_limit: i64,
        limit_flags: u32,
        minimum_working_set_size: usize,
        maximum_working_set_size: usize,
        active_process_limit: u32,
        affinity: usize,
        priority_class: u32,
        scheduling_class: u32,
    }

    #[repr(C)]
    #[derive(Default)]
    struct IoCounters {
        read_operation_count: u64,
        write_operation_count: u64,
        other_operation_count: u64,
        read_transfer_count: u64,
        write_transfer_count: u64,
        other_transfer_count: u64,
    }

    #[repr(C)]
    #[derive(Default)]
    struct ExtendedLimitInformation {
        basic_limit_information: BasicLimitInformation,
        io_info: IoCounters,
        process_memory_limit: usize,
        job_memory_limit: usize,
        peak_process_memory_used: usize,
        peak_job_memory_used: usize,
    }

    #[repr(C)]
    struct BasicAccountingInformation {
        total_user_time: i64,
        total_kernel_time: i64,
        this_period_total_user_time: i64,
        this_period_total_kernel_time: i64,
        total_page_fault_count: u32,
        total_processes: u32,
        active_processes: u32,
        total_terminated_processes: u32,
    }

    #[repr(C)]
    struct SecurityAttributes {
        length: u32,
        security_descriptor: *mut c_void,
        inherit_handle: i32,
    }

    #[repr(C)]
    struct StartupInfoW {
        cb: u32,
        reserved: *mut u16,
        desktop: *mut u16,
        title: *mut u16,
        x: u32,
        y: u32,
        x_size: u32,
        y_size: u32,
        x_chars: u32,
        y_chars: u32,
        fill_attribute: u32,
        flags: u32,
        show_window: u16,
        reserved2_size: u16,
        reserved2: *mut u8,
        stdin: Handle,
        stdout: Handle,
        stderr: Handle,
    }

    #[repr(C)]
    struct StartupInfoExW {
        startup_info: StartupInfoW,
        attribute_list: *mut c_void,
    }

    #[repr(C)]
    struct ProcessInformation {
        process: Handle,
        thread: Handle,
        process_id: u32,
        thread_id: u32,
    }

    #[link(name = "Kernel32")]
    extern "system" {
        fn CreateJobObjectW(attributes: *mut c_void, name: *const u16) -> Handle;
        fn SetInformationJobObject(
            job: Handle,
            information_class: i32,
            information: *const c_void,
            information_length: u32,
        ) -> i32;
        fn QueryInformationJobObject(
            job: Handle,
            information_class: i32,
            information: *mut c_void,
            information_length: u32,
            return_length: *mut u32,
        ) -> i32;
        fn AssignProcessToJobObject(job: Handle, process: Handle) -> i32;
        fn TerminateJobObject(job: Handle, exit_code: u32) -> i32;
        fn CreatePipe(
            read: *mut Handle,
            write: *mut Handle,
            attributes: *mut SecurityAttributes,
            size: u32,
        ) -> i32;
        fn SetHandleInformation(handle: Handle, mask: u32, flags: u32) -> i32;
        fn CreateFileW(
            name: *const u16,
            access: u32,
            share: u32,
            attributes: *mut SecurityAttributes,
            creation: u32,
            flags: u32,
            template: Handle,
        ) -> Handle;
        fn InitializeProcThreadAttributeList(
            list: *mut c_void,
            count: u32,
            flags: u32,
            size: *mut usize,
        ) -> i32;
        fn UpdateProcThreadAttribute(
            list: *mut c_void,
            flags: u32,
            attribute: usize,
            value: *mut c_void,
            size: usize,
            previous: *mut c_void,
            returned_size: *mut usize,
        ) -> i32;
        fn DeleteProcThreadAttributeList(list: *mut c_void);
        fn CreateProcessW(
            application: *const u16,
            command_line: *mut u16,
            process_attributes: *mut SecurityAttributes,
            thread_attributes: *mut SecurityAttributes,
            inherit_handles: i32,
            flags: u32,
            environment: *mut c_void,
            current_directory: *const u16,
            startup: *mut StartupInfoExW,
            information: *mut ProcessInformation,
        ) -> i32;
        fn ResumeThread(thread: Handle) -> u32;
        fn TerminateProcess(process: Handle, exit_code: u32) -> i32;
        fn WaitForSingleObject(handle: Handle, milliseconds: u32) -> u32;
        fn GetExitCodeProcess(process: Handle, exit_code: *mut u32) -> i32;
        fn PeekNamedPipe(
            pipe: Handle,
            buffer: *mut c_void,
            buffer_size: u32,
            bytes_read: *mut u32,
            total_bytes_available: *mut u32,
            bytes_left_this_message: *mut u32,
        ) -> i32;
        fn CloseHandle(handle: Handle) -> i32;
    }

    const INVALID_HANDLE_VALUE: isize = -1;
    const CREATE_SUSPENDED: u32 = 0x0000_0004;
    const CREATE_UNICODE_ENVIRONMENT: u32 = 0x0000_0400;
    const EXTENDED_STARTUPINFO_PRESENT: u32 = 0x0008_0000;
    const STARTF_USESTDHANDLES: u32 = 0x0000_0100;
    const PROC_THREAD_ATTRIBUTE_HANDLE_LIST: usize = 0x0002_0002;
    const WAIT_OBJECT_0: u32 = 0;
    const WAIT_TIMEOUT: u32 = 258;
    const WAIT_FAILED: u32 = u32::MAX;

    pub(super) struct WinHandle(Handle);

    impl WinHandle {
        fn new(handle: Handle) -> io::Result<Self> {
            if handle.is_null() || handle as isize == INVALID_HANDLE_VALUE {
                Err(io::Error::last_os_error())
            } else {
                Ok(Self(handle))
            }
        }

        fn raw(&self) -> Handle {
            self.0
        }

        fn into_file(mut self) -> File {
            let raw = self.0;
            self.0 = std::ptr::null_mut();
            // SAFETY: ownership of this valid pipe read handle moves to File.
            unsafe { File::from_raw_handle(raw) }
        }
    }

    impl Drop for WinHandle {
        fn drop(&mut self) {
            if !self.0.is_null() {
                // SAFETY: this wrapper uniquely owns the handle.
                unsafe { CloseHandle(self.0) };
            }
        }
    }

    struct Job(WinHandle);

    impl Job {
        fn new() -> io::Result<Self> {
            // SAFETY: null security attributes and name request a private job.
            let handle = unsafe { CreateJobObjectW(std::ptr::null_mut(), std::ptr::null()) };
            let job = Self(WinHandle::new(handle)?);
            let mut limits = ExtendedLimitInformation::default();
            // JOB_OBJECT_LIMIT_KILL_ON_JOB_CLOSE
            limits.basic_limit_information.limit_flags = 0x2000;
            // SAFETY: this is the documented extended-limit structure (class 9).
            let configured = unsafe {
                SetInformationJobObject(
                    job.0.raw(),
                    9,
                    (&limits as *const ExtendedLimitInformation).cast(),
                    size_of::<ExtendedLimitInformation>() as u32,
                )
            };
            if configured == 0 {
                return Err(io::Error::last_os_error());
            }
            Ok(job)
        }

        fn assign(&self, process: &WinHandle) -> io::Result<()> {
            // SAFETY: both handles remain owned and live during assignment.
            if unsafe { AssignProcessToJobObject(self.0.raw(), process.raw()) } == 0 {
                Err(io::Error::last_os_error())
            } else {
                Ok(())
            }
        }

        fn terminate_and_wait(&self) -> io::Result<()> {
            // SAFETY: the configured job handle is valid and owned by self.
            if unsafe { TerminateJobObject(self.0.raw(), 1) } == 0 {
                return Err(io::Error::last_os_error());
            }
            // Job handles are not a general termination barrier. Poll the
            // documented active-process accounting field instead.
            let deadline = Instant::now() + Duration::from_secs(2);
            loop {
                let mut accounting: BasicAccountingInformation = unsafe { zeroed() };
                // SAFETY: class 1 writes the documented basic accounting struct.
                let queried = unsafe {
                    QueryInformationJobObject(
                        self.0.raw(),
                        1,
                        (&mut accounting as *mut BasicAccountingInformation).cast(),
                        size_of::<BasicAccountingInformation>() as u32,
                        std::ptr::null_mut(),
                    )
                };
                if queried == 0 {
                    return Err(io::Error::last_os_error());
                }
                if accounting.active_processes == 0 {
                    return Ok(());
                }
                if Instant::now() >= deadline {
                    return Err(io::Error::new(
                        io::ErrorKind::TimedOut,
                        "Job Object processes did not terminate within 2 seconds",
                    ));
                }
                thread::sleep(Duration::from_millis(10));
            }
        }
    }

    struct AttributeList {
        pointer: *mut c_void,
        storage: Vec<usize>,
    }

    impl AttributeList {
        fn for_handles(handles: &[Handle]) -> io::Result<Self> {
            let mut bytes = 0usize;
            // SAFETY: null list requests the required storage size.
            unsafe {
                InitializeProcThreadAttributeList(std::ptr::null_mut(), 1, 0, &mut bytes);
            }
            if bytes == 0 {
                return Err(io::Error::last_os_error());
            }
            let mut storage = vec![0usize; bytes.div_ceil(size_of::<usize>())];
            let pointer = storage.as_mut_ptr().cast::<c_void>();
            // SAFETY: storage is large enough and pointer-aligned per API result.
            if unsafe { InitializeProcThreadAttributeList(pointer, 1, 0, &mut bytes) } == 0 {
                return Err(io::Error::last_os_error());
            }
            let list = Self { pointer, storage };
            // SAFETY: handles points to a live array copied into the attribute list.
            let updated = unsafe {
                UpdateProcThreadAttribute(
                    list.pointer,
                    0,
                    PROC_THREAD_ATTRIBUTE_HANDLE_LIST,
                    handles.as_ptr().cast_mut().cast(),
                    size_of::<Handle>() * handles.len(),
                    std::ptr::null_mut(),
                    std::ptr::null_mut(),
                )
            };
            if updated == 0 {
                return Err(io::Error::last_os_error());
            }
            Ok(list)
        }
    }

    impl Drop for AttributeList {
        fn drop(&mut self) {
            // Keep storage alive for the lifetime of the initialized list.
            let _ = self.storage.len();
            // SAFETY: this list was initialized successfully and is uniquely owned.
            unsafe { DeleteProcThreadAttributeList(self.pointer) };
        }
    }

    fn wide(value: &OsStr) -> Vec<u16> {
        value.encode_wide().chain(Some(0)).collect()
    }

    fn quote_windows_arg(value: &OsStr) -> Vec<u16> {
        let units: Vec<u16> = value.encode_wide().collect();
        let mut result = Vec::with_capacity(units.len() + 2);
        result.push(b'"' as u16);
        let mut slashes = 0usize;
        for unit in units {
            if unit == b'\\' as u16 {
                slashes += 1;
            } else if unit == b'"' as u16 {
                result.extend(std::iter::repeat(b'\\' as u16).take(slashes * 2 + 1));
                result.push(unit);
                slashes = 0;
            } else {
                result.extend(std::iter::repeat(b'\\' as u16).take(slashes));
                result.push(unit);
                slashes = 0;
            }
        }
        result.extend(std::iter::repeat(b'\\' as u16).take(slashes * 2));
        result.push(b'"' as u16);
        result
    }

    fn command_line(executable: &OsStr, command: &str) -> Vec<u16> {
        let mut result = quote_windows_arg(executable);
        result.extend(" /D /S /C ".encode_utf16());
        result.extend(quote_windows_arg(OsStr::new(command)));
        result.push(0);
        result
    }

    fn environment_block(
        environment: &std::collections::HashMap<std::ffi::OsString, std::ffi::OsString>,
    ) -> Vec<u16> {
        let mut entries: Vec<_> = environment.iter().collect();
        entries.sort_by_key(|(key, _)| key.to_string_lossy().to_lowercase());
        let mut block = Vec::new();
        for (key, value) in entries {
            block.extend(key.encode_wide());
            block.push(b'=' as u16);
            block.extend(value.encode_wide());
            block.push(0);
        }
        if block.is_empty() {
            block.push(0);
        }
        block.push(0);
        block
    }

    fn make_pipe() -> io::Result<(WinHandle, WinHandle)> {
        let mut attributes = SecurityAttributes {
            length: size_of::<SecurityAttributes>() as u32,
            security_descriptor: std::ptr::null_mut(),
            inherit_handle: 1,
        };
        let mut read = std::ptr::null_mut();
        let mut write = std::ptr::null_mut();
        // SAFETY: output pointers and inheritable security attributes are valid.
        let created = unsafe { CreatePipe(&mut read, &mut write, &mut attributes, 0) };
        if created == 0 {
            let error = io::Error::last_os_error();
            if !read.is_null() {
                // SAFETY: clean up any partial handle returned by the API.
                unsafe { CloseHandle(read) };
            }
            if !write.is_null() {
                // SAFETY: clean up any partial handle returned by the API.
                unsafe { CloseHandle(write) };
            }
            return Err(error);
        }
        let read = WinHandle(read);
        let write = WinHandle(write);
        // Parent read handles must not be inherited by the shell.
        // SAFETY: read is a valid pipe handle owned here.
        if unsafe { SetHandleInformation(read.raw(), 1, 0) } == 0 {
            return Err(io::Error::last_os_error());
        }
        Ok((read, write))
    }

    pub(super) struct LaunchedProcess {
        pub(super) process: WinHandle,
        stdout: Option<File>,
        stderr: Option<File>,
        job: Option<Job>,
    }

    impl LaunchedProcess {
        pub(super) fn take_stdout(&mut self) -> File {
            self.stdout.take().expect("stdout pipe is present")
        }

        pub(super) fn take_stderr(&mut self) -> File {
            self.stderr.take().expect("stderr pipe is present")
        }

        pub(super) fn terminate_and_wait(&mut self) -> io::Result<()> {
            let Some(job) = self.job.take() else {
                return Ok(());
            };
            match job.terminate_and_wait() {
                Ok(()) => Ok(()),
                Err(error) => {
                    // Closing the last job handle invokes KILL_ON_JOB_CLOSE.
                    drop(job);
                    // SAFETY: reap the root process after the kill-on-close fallback.
                    match unsafe { WaitForSingleObject(self.process.raw(), u32::MAX) } {
                        WAIT_OBJECT_0 => Err(error),
                        WAIT_FAILED => Err(io::Error::last_os_error()),
                        _ => Err(error),
                    }
                }
            }
        }
    }

    pub(super) fn launch(
        command: &str,
        cwd: Option<&str>,
        environment: &std::collections::HashMap<std::ffi::OsString, std::ffi::OsString>,
    ) -> io::Result<LaunchedProcess> {
        let job = Job::new()?;
        let (stdout_read, stdout_write) = make_pipe()?;
        let (stderr_read, stderr_write) = make_pipe()?;
        let mut security = SecurityAttributes {
            length: size_of::<SecurityAttributes>() as u32,
            security_descriptor: std::ptr::null_mut(),
            inherit_handle: 1,
        };
        let stdin_name = [b'N' as u16, b'U' as u16, b'L' as u16, 0];
        // SECURITY_ATTRIBUTES makes the NUL stdin inheritable, then the
        // explicit handle list below limits inheritance to these three handles.
        // SAFETY: arguments describe an existing NUL device and valid attributes.
        let stdin = WinHandle::new(unsafe {
            CreateFileW(
                stdin_name.as_ptr(),
                0x8000_0000,
                3,
                &mut security,
                3,
                0x80,
                std::ptr::null_mut(),
            )
        })?;
        let inherited = [stdin.raw(), stdout_write.raw(), stderr_write.raw()];
        let attributes = AttributeList::for_handles(&inherited)?;
        let mut startup: StartupInfoExW = unsafe { zeroed() };
        startup.startup_info.cb = size_of::<StartupInfoExW>() as u32;
        startup.startup_info.flags = STARTF_USESTDHANDLES;
        startup.startup_info.stdin = stdin.raw();
        startup.startup_info.stdout = stdout_write.raw();
        startup.startup_info.stderr = stderr_write.raw();
        startup.attribute_list = attributes.pointer;

        let system_root = std::env::var_os("SystemRoot")
            .ok_or_else(|| io::Error::new(io::ErrorKind::NotFound, "SystemRoot is unavailable"))?;
        let executable = Path::new(&system_root).join("System32").join("cmd.exe");
        let executable_wide = wide(executable.as_os_str());
        let mut line = command_line(executable.as_os_str(), command);
        let mut cwd_wide = cwd.map(|value| wide(OsStr::new(value)));
        let mut env = environment_block(environment);
        let mut information: ProcessInformation = unsafe { zeroed() };
        // SAFETY: all pointers reference live mutable buffers; handle inheritance
        // is restricted by PROC_THREAD_ATTRIBUTE_HANDLE_LIST. The process starts
        // suspended and its returned primary-thread handle is retained below.
        let created = unsafe {
            CreateProcessW(
                executable_wide.as_ptr(),
                line.as_mut_ptr(),
                std::ptr::null_mut(),
                std::ptr::null_mut(),
                1,
                CREATE_SUSPENDED | CREATE_UNICODE_ENVIRONMENT | EXTENDED_STARTUPINFO_PRESENT,
                env.as_mut_ptr().cast(),
                cwd_wide
                    .as_mut()
                    .map_or(std::ptr::null(), |value| value.as_mut_ptr()),
                &mut startup,
                &mut information,
            )
        };
        if created == 0 {
            return Err(io::Error::last_os_error());
        }
        if information.process.is_null() || information.thread.is_null() {
            if !information.process.is_null() {
                // SAFETY: CreateProcessW reported success; this is its process handle.
                unsafe { TerminateProcess(information.process, 1) };
                // SAFETY: wait before closing the process handle.
                unsafe { WaitForSingleObject(information.process, u32::MAX) };
                // SAFETY: close the process handle returned by CreateProcessW.
                unsafe { CloseHandle(information.process) };
            }
            if !information.thread.is_null() {
                // SAFETY: close the thread handle returned by CreateProcessW.
                unsafe { CloseHandle(information.thread) };
            }
            return Err(io::Error::other(
                "CreateProcessW returned incomplete process information",
            ));
        }
        let process = WinHandle(information.process);
        let thread = WinHandle(information.thread);
        drop(stdin);
        drop(stdout_write);
        drop(stderr_write);

        // Assignment failure (including a restrictive outer Job Object) is
        // fail-closed: terminate/reap the still-suspended child before returning.
        if let Err(error) = job.assign(&process) {
            // SAFETY: process is a valid suspended process handle.
            unsafe { TerminateProcess(process.raw(), 1) };
            // SAFETY: wait for the terminated child before dropping its handles.
            unsafe { WaitForSingleObject(process.raw(), u32::MAX) };
            return Err(error);
        }

        // Resume the exact primary thread handle returned by CreateProcessW.
        // A CREATE_SUSPENDED process must have a suspend count of exactly one.
        // SAFETY: thread is the primary-thread handle in PROCESS_INFORMATION.
        let previous_count = unsafe { ResumeThread(thread.raw()) };
        if previous_count != 1 {
            let error = if previous_count == u32::MAX {
                io::Error::last_os_error()
            } else {
                io::Error::other(format!(
                    "unexpected primary thread suspend count: {previous_count}"
                ))
            };
            let _ = job.terminate_and_wait();
            // SAFETY: fallback termination covers an unexpected job wait failure.
            unsafe { TerminateProcess(process.raw(), 1) };
            // SAFETY: reap the root process before returning.
            unsafe { WaitForSingleObject(process.raw(), u32::MAX) };
            return Err(error);
        }
        drop(thread);

        Ok(LaunchedProcess {
            process,
            stdout: Some(stdout_read.into_file()),
            stderr: Some(stderr_read.into_file()),
            job: Some(job),
        })
    }

    pub(super) fn wait(process: &WinHandle, milliseconds: u32) -> io::Result<bool> {
        // SAFETY: process is a live process handle retained by LaunchedProcess.
        match unsafe { WaitForSingleObject(process.raw(), milliseconds) } {
            WAIT_OBJECT_0 => Ok(true),
            WAIT_TIMEOUT => Ok(false),
            WAIT_FAILED => Err(io::Error::last_os_error()),
            _ => Err(io::Error::other("unexpected process wait result")),
        }
    }

    pub(super) fn exit_code(process: &WinHandle) -> io::Result<i32> {
        let mut code = 0u32;
        // SAFETY: process is signaled and code points to writable storage.
        if unsafe { GetExitCodeProcess(process.raw(), &mut code) } == 0 {
            Err(io::Error::last_os_error())
        } else {
            Ok(code as i32)
        }
    }

    pub(super) unsafe fn peek_available(pipe: Handle, available: &mut u32) -> bool {
        // SAFETY: optional output pointers are null; `available` is writable.
        unsafe {
            PeekNamedPipe(
                pipe,
                std::ptr::null_mut(),
                0,
                std::ptr::null_mut(),
                available,
                std::ptr::null_mut(),
            ) != 0
        }
    }
}

#[cfg(unix)]
fn terminate_tree(child: &mut Child) {
    // The shell is put in a fresh process group before it starts, so this
    // signal reaches ordinary descendants even if the shell itself exits.
    let group = -(child.id() as i32);
    // SAFETY: kill with a negative pid targets the process group created
    // for this child; the signal and pid are valid integers.
    unsafe {
        libc::kill(group, libc::SIGTERM);
    }
    thread::sleep(TERMINATE_GRACE);
    // SAFETY: same process-group target, escalated to guarantee cleanup.
    unsafe {
        libc::kill(group, libc::SIGKILL);
    }
    let _ = child.kill();
}

fn spawn_error(error: io::Error, timeout_used: u64) -> ShellExecOutput {
    ShellExecOutput {
        content: format!("Failed to execute: {error}"),
        success: false,
        returncode: -1,
        timed_out: false,
        stdout_truncated: false,
        stderr_truncated: false,
        timeout_used,
    }
}

fn build_output(
    stdout: Vec<u8>,
    stderr: Vec<u8>,
    returncode: i32,
    exit_success: bool,
    timed_out: bool,
    output_limited: bool,
    stdout_truncated: bool,
    stderr_truncated: bool,
    timeout_used: u64,
) -> ShellExecOutput {
    let stdout = String::from_utf8_lossy(&stdout);
    let stderr = String::from_utf8_lossy(&stderr);
    let mut content = format!(
        "Exit code: {returncode}\n--- stdout ---\n{stdout}\n--- stderr ---\n{stderr}"
    );
    if timed_out {
        content = format!("Command timed out.\n{content}");
    }
    if output_limited {
        content = format!("Output limit reached; process tree terminated.\n{content}");
    }
    if stdout_truncated {
        content.push_str(STDOUT_TRUNCATION_MARKER);
    }
    if stderr_truncated {
        content.push_str(STDERR_TRUNCATION_MARKER);
    }
    ShellExecOutput {
        content,
        success: exit_success && !timed_out && !output_limited,
        returncode,
        timed_out,
        stdout_truncated,
        stderr_truncated,
        timeout_used,
    }
}

#[cfg(unix)]
fn run_detailed(params: &Value) -> (ShellExecOutput, bool) {
    let command = params["command"].as_str().unwrap_or("");
    let cwd = params["cwd"].as_str();
    let timeout = Duration::from_secs(timeout_seconds(params));
    let mut cmd = Command::new("sh");
    cmd.args(["-c", command])
        .env_clear()
        .envs(platform_environment())
        .stdin(Stdio::null())
        .stdout(Stdio::piped())
        .stderr(Stdio::piped());
    if let Some(dir) = cwd {
        cmd.current_dir(dir);
    }
    use std::os::unix::process::CommandExt;
    cmd.process_group(0);

    let mut child = match cmd.spawn() {
        Ok(child) => child,
        Err(error) => return (spawn_error(error, timeout.as_secs()), false),
    };
    let stdout = child.stdout.take().expect("piped stdout");
    let stderr = child.stderr.take().expect("piped stderr");
    let remaining_budget = Arc::new(Mutex::new(MAX_CAPTURE_BYTES));
    let output_exceeded = Arc::new(AtomicBool::new(false));
    let stdout_reader = thread::spawn({
        let budget = Arc::clone(&remaining_budget);
        let limited = Arc::clone(&output_exceeded);
        move || bounded_reader(stdout, budget, limited)
    });
    let stderr_reader = thread::spawn({
        let limited = Arc::clone(&output_exceeded);
        move || bounded_reader(stderr, remaining_budget, limited)
    });

    let deadline = Instant::now() + timeout;
    let mut timed_out = false;
    let mut output_limit_terminated = false;
    let status = loop {
        if output_exceeded.load(Ordering::Acquire) {
            match child.try_wait() {
                Ok(Some(status)) => break Some(status),
                Ok(None) => {
                    output_limit_terminated = true;
                    terminate_tree(&mut child);
                    break child.wait().ok();
                }
                Err(_) => {
                    terminate_tree(&mut child);
                    break child.wait().ok();
                }
            }
        }
        match child.try_wait() {
            Ok(Some(status)) => break Some(status),
            Ok(None) if Instant::now() < deadline => thread::sleep(POLL_INTERVAL),
            Ok(None) => {
                timed_out = true;
                terminate_tree(&mut child);
                break child.wait().ok();
            }
            Err(_) => {
                terminate_tree(&mut child);
                break child.wait().ok();
            }
        }
    };

    // The shell can exit while descendants still own pipe handles.
    if !timed_out && !output_limit_terminated {
        let group = -(child.id() as i32);
        // SAFETY: this targets only the isolated process group created above.
        unsafe { libc::kill(group, libc::SIGKILL) };
    }
    let (stdout, stdout_truncated) = stdout_reader
        .join()
        .unwrap_or_default();
    let (stderr, stderr_truncated) = stderr_reader
        .join()
        .unwrap_or_default();
    let returncode = if timed_out {
        -1
    } else {
        status.as_ref().and_then(|status| status.code()).unwrap_or(-1)
    };
    let exit_success = status.as_ref().is_some_and(|status| status.success());
    let output = build_output(
        stdout,
        stderr,
        returncode,
        exit_success,
        timed_out,
        output_limit_terminated,
        stdout_truncated,
        stderr_truncated,
        timeout.as_secs(),
    );
    (output, output_limit_terminated)
}

#[cfg(windows)]
fn run_detailed(params: &Value) -> (ShellExecOutput, bool) {
    use windows_native::{exit_code, launch, wait};

    let timeout_seconds = timeout_seconds(params);
    let timeout = Duration::from_secs(timeout_seconds);
    let environment = platform_environment();
    let mut process = match launch(
        params["command"].as_str().unwrap_or(""),
        params["cwd"].as_str(),
        &environment,
    ) {
        Ok(process) => process,
        Err(error) => return (spawn_error(error, timeout_seconds), false),
    };
    let remaining_budget = Arc::new(Mutex::new(MAX_CAPTURE_BYTES));
    let output_exceeded = Arc::new(AtomicBool::new(false));
    let readers_stop = Arc::new(AtomicBool::new(false));
    let stdout = process.take_stdout();
    let stderr = process.take_stderr();
    let stdout_reader = thread::spawn({
        let budget = Arc::clone(&remaining_budget);
        let limited = Arc::clone(&output_exceeded);
        let stop = Arc::clone(&readers_stop);
        move || bounded_reader_windows(stdout, budget, limited, stop)
    });
    let stderr_reader = thread::spawn({
        let limited = Arc::clone(&output_exceeded);
        let stop = Arc::clone(&readers_stop);
        move || bounded_reader_windows(stderr, remaining_budget, limited, stop)
    });

    let deadline = Instant::now() + timeout;
    let mut timed_out = false;
    let mut wait_failed = false;
    let mut output_limit_terminated = false;
    loop {
        if output_exceeded.load(Ordering::Acquire) {
            match wait(&process.process, 0) {
                Ok(true) => break,
                Ok(false) => output_limit_terminated = true,
                Err(_) => wait_failed = true,
            }
            break;
        }
        let now = Instant::now();
        if now >= deadline {
            timed_out = true;
            break;
        }
        let remaining = deadline.saturating_duration_since(now);
        let interval = remaining.min(POLL_INTERVAL).as_millis().max(1) as u32;
        match wait(&process.process, interval) {
            Ok(true) => break,
            Ok(false) => {}
            Err(_) => {
                wait_failed = true;
                break;
            }
        }
    }
    let process_exited = wait(&process.process, 0).unwrap_or(false);
    let code = if process_exited {
        exit_code(&process.process).unwrap_or(-1)
    } else {
        -1
    };
    let cleanup_failed = process.terminate_and_wait().is_err();
    readers_stop.store(true, Ordering::Release);
    let (stdout, stdout_truncated) = stdout_reader
        .join()
        .unwrap_or_default();
    let (stderr, stderr_truncated) = stderr_reader
        .join()
        .unwrap_or_default();
    let returncode = if timed_out || wait_failed || !process_exited { -1 } else { code };
    let mut result = build_output(
        stdout,
        stderr,
        returncode,
        returncode == 0 && !cleanup_failed,
        timed_out,
        output_limit_terminated,
        stdout_truncated,
        stderr_truncated,
        timeout_seconds,
    );
    if cleanup_failed {
        result.success = false;
        result.content = format!("Process tree cleanup failed.\n{}", result.content);
    }
    (result, output_limit_terminated)
}

fn run(params: &Value) -> ShellExecOutput {
    run_detailed(params).0
}

impl BaseTool for ShellExecTool {
    fn tool_id(&self) -> &str {
        "shell_exec"
    }
    fn spec(&self) -> &ToolSpec {
        &SPEC
    }
    fn execute(&self, params: &Value) -> Result<ToolResult, OpenJarvisError> {
        let (output, output_limited) = run_detailed(params);
        let mut result = if output.success {
            ToolResult::success("shell_exec", output.content)
        } else {
            ToolResult::failure("shell_exec", output.content)
        };
        result.metadata.insert("returncode".into(), output.returncode.into());
        result.metadata.insert("timed_out".into(), output.timed_out.into());
        result.metadata.insert("output_limited".into(), output_limited.into());
        result.metadata.insert("stdout_truncated".into(), output.stdout_truncated.into());
        result.metadata.insert("stderr_truncated".into(), output.stderr_truncated.into());
        result.metadata.insert("timeout_used".into(), output.timeout_used.into());
        Ok(result)
    }
}

impl ShellExecTool {
    /// Execute and return typed process status for the PyO3 wrapper.
    pub fn execute_structured(&self, params: &Value) -> ShellExecOutput {
        run(params)
    }

    /// Execute and include whether the output cap forced process-tree cleanup.
    pub fn execute_structured_with_limit(&self, params: &Value) -> (ShellExecOutput, bool) {
        run_detailed(params)
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use serde_json::json;

    #[test]
    fn reports_nonzero_exit_as_failure() {
        let result = run(&json!({
            "command": if cfg!(windows) { "exit /b 42" } else { "exit 42" }
        }));
        assert!(!result.success);
        assert_eq!(result.returncode, 42);
        assert!(!result.timed_out);
    }

    #[test]
    fn clamps_timeout_to_supported_range() {
        assert_eq!(timeout_seconds(&json!({})), DEFAULT_TIMEOUT_SECONDS);
        assert_eq!(timeout_seconds(&json!({"timeout": 0})), 1);
        assert_eq!(timeout_seconds(&json!({"timeout": 999})), MAX_TIMEOUT_SECONDS);
    }

    #[test]
    fn ignores_model_supplied_environment_passthrough() {
        const MARKER: &str = "OPENJARVIS_WP2_TEST_PARENT_SECRET";
        const API_MARKER: &str = "OPENJARVIS_WP2_DUMMY_API_TOKEN";
        std::env::set_var(MARKER, "dummy-parent-secret");
        std::env::set_var(API_MARKER, "dummy-api-key");
        let command = if cfg!(windows) {
            format!("echo %{MARKER}% %{API_MARKER}%")
        } else {
            format!("printf '%s %s' \"${MARKER}\" \"${API_MARKER}\"")
        };
        let result = run(&json!({
            "command": command,
            "env_passthrough": [MARKER, API_MARKER]
        }));
        assert!(!result.content.contains("dummy-parent-secret"));
        assert!(!result.content.contains("dummy-api-key"));
        std::env::remove_var(MARKER);
        std::env::remove_var(API_MARKER);
    }

    #[cfg(unix)]
    #[test]
    fn combined_output_budget_bounds_simultaneous_stream_flooding() {
        let command = concat!(
            "head -c 200000 /dev/zero | tr '\\0' A & ",
            "head -c 200000 /dev/zero | tr '\\0' B >&2 & wait"
        );
        let result = run(&json!({"command": command}));
        assert!(result.stdout_truncated);
        assert!(result.stderr_truncated);
        let stdout_start = result.content.find("--- stdout ---\n").unwrap() + 15;
        let stderr_start = result.content.find("--- stderr ---\n").unwrap() + 15;
        let stdout = &result.content[stdout_start..stderr_start];
        let stderr = &result.content[stderr_start..];
        let captured = stdout.matches('A').count() + stderr.matches('B').count();
        assert!(captured <= MAX_CAPTURE_BYTES);
    }

    #[cfg(unix)]
    #[test]
    fn continuous_output_after_budget_exhaustion_terminates_the_process_group() {
        let started = Instant::now();
        let result = run(&json!({
            "command": "while :; do printf x; done",
            "timeout": 30
        }));

        assert!(result.stdout_truncated || result.stderr_truncated);
        assert!(!result.timed_out);
        assert!(!result.success);
        assert!(result.stdout_truncated || result.stderr_truncated);
        assert!(started.elapsed() < Duration::from_secs(5));
        assert!(result.content.len() <= MAX_OUTPUT_BYTES + 1024);
    }

    #[cfg(windows)]
    #[test]
    fn continuous_output_after_budget_exhaustion_terminates_the_job() {
        let started = Instant::now();
        let result = run(&json!({
            "command": "for /L %i in (1,1,2147483647) do @echo x",
            "timeout": 30
        }));

        assert!(result.stdout_truncated || result.stderr_truncated);
        assert!(!result.timed_out);
        assert!(!result.success);
        assert!(result.stdout_truncated || result.stderr_truncated);
        assert!(started.elapsed() < Duration::from_secs(5));
        assert!(result.content.len() <= MAX_OUTPUT_BYTES + 1024);
    }

    #[cfg(unix)]
    #[test]
    fn timeout_kills_process_group() {
        let marker = tempfile::NamedTempFile::new().unwrap();
        let path = marker.path().to_string_lossy().into_owned();
        let command = format!("sleep 60 & child=$!; echo $child > '{path}'; wait");
        let result = run(&json!({"command": command, "timeout": 1}));
        assert!(result.timed_out);
        assert!(!result.success);
        let child_pid = std::fs::read_to_string(&path).unwrap();
        let child_pid = child_pid.trim().parse().unwrap();
        let deadline = Instant::now() + Duration::from_secs(2);
        loop {
            // SAFETY: signal zero only checks whether this test child exists.
            let alive = unsafe { libc::kill(child_pid, 0) == 0 };
            if !alive || Instant::now() >= deadline {
                assert!(!alive, "timed out shell descendant is still alive");
                break;
            }
            thread::sleep(Duration::from_millis(20));
        }
    }

    #[cfg(unix)]
    #[test]
    fn normal_shell_exit_closes_descendant_stdout_and_stderr() {
        for command in ["sleep 60 & exit 0", "sleep 60 >&2 & exit 0"] {
            let started = Instant::now();
            let result = run(&json!({"command": command, "timeout": 2}));
            assert!(result.success);
            assert!(started.elapsed() < Duration::from_secs(3));
        }
    }

    #[cfg(windows)]
    #[test]
    fn timeout_kills_windows_process_tree() {
        let marker = tempfile::NamedTempFile::new().unwrap();
        let path = marker.path().to_string_lossy().replace('\'', "''");
        let command = format!(
            "start \"\" /b powershell.exe -NoProfile -Command \"$PID | Out-File -NoNewline -Encoding ascii '{path}'; Start-Sleep -Seconds 60\" & ping -n 60 127.0.0.1 >nul"
        );
        let result = run(&json!({"command": command, "timeout": 1}));
        assert!(result.timed_out);
        let child_pid = std::fs::read_to_string(path.as_ref()).unwrap();
        let listing = Command::new("tasklist")
            .args(["/FI", &format!("PID eq {}", child_pid.trim()), "/FO", "CSV", "/NH"])
            .output()
            .unwrap();
        let listing = String::from_utf8_lossy(&listing.stdout);
        assert!(!listing.contains(child_pid.trim()), "timed out shell descendant is still alive");
    }

    #[cfg(windows)]
    #[test]
    fn normal_shell_exit_closes_descendant_stdout_and_stderr() {
        for command in [
            "start \"\" /b powershell.exe -NoProfile -Command \"Write-Output child-stdout; Start-Sleep -Seconds 30\" & exit /b 0",
            "start \"\" /b powershell.exe -NoProfile -Command \"[Console]::Error.WriteLine('child-stderr'); Start-Sleep -Seconds 30\" & exit /b 0",
        ] {
            let started = Instant::now();
            let result = run(&json!({"command": command, "timeout": 2}));
            assert!(result.success);
            assert!(started.elapsed() < Duration::from_secs(5));
        }
    }

    #[test]
    fn spawn_failure_is_a_structured_failure() {
        let directory = tempfile::tempdir().unwrap();
        let missing = directory.path().join("missing-child-cwd");
        let result = run(&json!({"command": "echo hi", "cwd": missing}));
        assert!(!result.success);
        assert_eq!(result.returncode, -1);
    }

    #[cfg(unix)]
    #[test]
    fn preserves_unicode_output() {
        let result = run(&json!({"command": "printf 'héllo 世界'"}));
        assert!(result.success);
        assert!(result.content.contains("héllo 世界"));
    }
}
