# OpenJarvis: sizing và danh mục phần cứng edge/kiosk (11-09-2026)

## Quyết định đề xuất

**Không phê duyệt Jetson Orin Nano 8 GB cho kiosk đầy đủ.** Bộ nhớ hợp nhất 8 GB không còn đủ khi thêm đỉnh đồng thời của SCRFD, MiniFASNet, Metric3D, WebRTC/VAD/TTS, compositor và một Agent/LLM cục bộ; với hệ số dự phòng 35%, mức đỉnh an toàn chỉ là `8 / 1.35 = 5.93 GB` cho toàn hệ thống.

**Cấu hình mặc định nên mua cho kiosk đầy đủ:** máy SFF x86-64 công nghiệp/desktop có **NVIDIA RTX PRO 4000 Blackwell SFF 24 GB ECC, 64 GB DDR5, NVMe 2 TB, nguồn 550 W hoặc lớn hơn và Ubuntu 24.04 LTS**. Card có 24 GB GDDR7 ECC, 432 GB/s, 70 W, PCIe Gen5, kích thước 2.7 x 6.6 inch/dual-slot và 770 AI TOPS do hãng công bố; mức VRAM peak được phép ở headroom 35% là `17.78 GB`. [NVIDIA RTX PRO 4000 SFF](https://www.nvidia.com/en-us/products/workstations/professional-desktop-gpus/rtx-pro-4000-sff/)  
Điều này là lựa chọn cân bằng nhất giữa VRAM, nhiệt, âm học và khả năng chạy cùng một runtime x86/CUDA hiện hữu. TOPS chỉ là throughput lý thuyết, **không phải** FPS/độ trễ của OpenJarvis.

**Phương án thay thế theo ràng buộc:**

| Trường hợp triển khai | Thiết bị nên chọn | Điều kiện chấp nhận |
|---|---|---|
| Kiosk đầy đủ, nhiều camera/âm thanh, cần độ ổn định 24/7 | x86 SFF + RTX PRO 4000 Blackwell SFF 24 GB ECC | Peak VRAM OpenJarvis phải <= 17.78 GB; burn-in nhiệt/ồn đạt ngưỡng bên dưới. |
| Kiosk gắn kín, cần vòng đời module/nguồn DC và camera MIPI | Jetson AGX Orin Industrial 64 GB + carrier/chassis công nghiệp | Port ARM64 và mọi wheel ONNX/TTS phải pass; peak RAM hợp nhất <= 47.41 GB. |
| Kiosk vision-first, Agent/LLM ở dịch vụ khác | Jetson Orin NX 16 GB + carrier sản xuất | Peak RAM hợp nhất <= 11.85 GB; không coi là cấu hình đầy đủ trước khi test full-duplex. |
| Bàn phát triển LLM cục bộ/UMA, không cần MIPI | NVIDIA DGX Spark 128 GB | Kiểm thử ARM64, camera USB và nhiệt/ồn; không phải appliance kiosk mặc định. |

Không chốt PO chỉ từ benchmark nhàn rỗi hiện có. Cần hoàn thành cổng đo peak ở phần 3; sau đó áp dụng ma trận quyết định tại phần 9.

## 1. Phạm vi, nguyên tắc nguồn và các loại trừ

- Chỉ xét thiết bị đã thương mại hóa và có Linux/CUDA. Jetson dùng JetPack: JetPack cung cấp Jetson Linux/Ubuntu, CUDA, TensorRT và các thư viện tăng tốc; ONNX Runtime có TensorRT EP và CUDA EP, đồng thời có gói/containers cho JetPack. [JetPack](https://developer.nvidia.com/embedded/jetpack) [ONNX Runtime TensorRT EP](https://onnxruntime.ai/docs/execution-providers/TensorRT-ExecutionProvider.html)
- Bỏ CPU-only, thin client/cloud-only, Jetson developer kit trong BOM sản xuất (NVIDIA nói developer kit chỉ cho phát triển; production phải dùng module + carrier/chassis). [Jetson FAQ](https://developer.nvidia.com/embedded/faq)
- Bỏ TX2/Xavier cũ và các SKU EOL/NCNR. Vòng đời chính thức của Orin thương mại kéo tới tháng 01-2032, Industrial tới tháng 07-2033. [Jetson lifecycle](https://developer.nvidia.com/embedded/lifecycle)
- Thông số hãng được ghi là **công bố**. MLPerf Edge dùng để đối chiếu phương pháp chuẩn nhưng không thay thế workload OpenJarvis: model, độ phân giải, batch, TensorRT build và constraint latency khác nhau. [MLPerf Edge](https://mlcommons.org/benchmarks/inference-edge/)
- Giá/tồn kho/lead time là dữ liệu biến động theo region, số lượng và Incoterms. Bảng giá dưới đây là mốc công khai USD, chưa thuế/chưa vận chuyển; PO tại Việt Nam chỉ được phát hành sau RFQ cùng SKU/carrier/chassis với ít nhất hai đại lý NVIDIA ủy quyền.

## 2. Cơ sở đo được trên OpenJarvis hiện tại

### 2.1 Thiết bị đang đo

Máy hiện tại: Intel Core i7-11800H (8 lõi vật lý/16 logical), RAM 15.31 GiB, laptop RTX 3050 Ti 4 GiB. Stack đang chạy gồm `vision`, `backend`, `frontend` và các tiến trình con/MCP; vision chứa SCRFD, MiniFASNet và Metric3D; voice có Silero VAD, Gemini STT, VieNeu TTS ONNX và WebRTC; Agent chạy riêng trong backend.

### 2.2 Snapshot trực tiếp, không phải peak acceptance

Lệnh đã chạy khi stack hiện hữu hoạt động (PID vision 6842, backend 6845, frontend 6876):

```bash
uv run jarvis bench stack --pid 6842 --pid 6845 --pid 6876 \
  --seconds 30 --interval 1 \
  --output /tmp/openjarvis-stack/stack-benchmark-20260911T1430.jsonl
```

| Chỉ số 29 mẫu/30 s | P95 | Peak | Diễn giải đúng |
|---|---:|---:|---|
| PSS process-tree | 2.138 GiB | 2.139 GiB | RAM thực chia sẻ theo Linux; không phải RAM toàn máy. |
| RSS process-tree | 3.042 GiB | 3.043 GiB | Có double-count shared pages, chỉ dùng theo dõi. |
| CPU | 77.16% một core | 83.62% một core | Không có hard cap một core; tổng tải lúc đó dưới một logical core. |
| GPU utilisation | 46.2% | 48.0% | Snapshot có burst, không suy ra GPU cần thiết. |
| GPU memory reported | 922 MiB | 922 MiB | NVML toàn GPU, không gán riêng cho OpenJarvis. |
| Tiến trình trong tree | 15 | 15 | Bao gồm descendants của ba root PID. |

Kết luận từ snapshot: nó loại trừ nhận định “stack đang cần 4 GB VRAM peak”, nhưng **không đủ** để kết luận về VRAM/RAM bandwidth/nhiệt ở tải thật. Chưa có camera đúng độ phân giải, turn thoại full-duplex liên tục, TTS đồng thời, Agent tool-use, CUDA-kernel trace, wall-power và ambient được khóa trong 30 giây này.

Lý do CPU có vẻ chỉ dùng khoảng một core không phải hard-code: hiện launcher ưu tiên thread-count ONNX thấp cho VieNeu vì tăng thread từng không cải thiện RTF tương xứng. Đây là lựa chọn latency/RTF của TTS; Metric3D/CUDA, decode camera và Node/Python vẫn có thể tạo burst riêng. Vì vậy CPU phải sizing bằng P95/peak của kịch bản hội tụ, không dùng snapshot nhàn rỗi.

## 3. Cổng đo bắt buộc trước khi chốt BOM

Chạy mỗi kịch bản tối thiểu 30 phút sau warm-up 10 phút, lặp lại ba lần, ambient ghi nhận, nguồn và camera đúng BOM. Mỗi lần lưu raw JSON/CSV, commit hash, model hash, driver/CUDA/JetPack và cấu hình power mode.

| Kịch bản hội tụ | Tác vụ đồng thời | Số đo bắt buộc | Pass/Fail cần suy ra |
|---|---|---|---|
| Kiosk vision peak | 1–2 camera mục tiêu, SCRFD + MiniFASNet + Metric3D, kiosk 5 Hz | FPS, age frame P50/P95/P99, `nvidia-smi dmon` hoặc `tegrastats`, VRAM/RAM, GPU clocks/throttle | Không rớt FPS/SLA; không OOM; headroom còn >=25%. |
| Voice full-duplex | âm thanh capture/playback, VAD, Gemini STT, VieNeu TTS, Agent streaming | end-of-utterance-to-first-audio, RTF, XRUN/packet loss, CPU per-thread, audio latency | P95 đáp ứng product SLA, zero XRUN trong soak. |
| Hội tụ xấu nhất | vision peak + voice turn + Agent/tool action + UI | tất cả trên, CUDA kernel trace, H2D/D2H copy, memory BW, I/O USB | Đây là nguồn duy nhất được dùng sizing. |
| Soak nhiệt | kịch bản hội tụ, 8 h rồi 24 h | nhiệt GPU/CPU/SSD, fan RPM/dBA, clock, power, restart/error count | Không thermal throttle bền vững; nhiệt margin tại ambient mục tiêu. |

Lệnh/công cụ: x86 NVIDIA dùng `nvidia-smi --query-gpu=timestamp,utilization.gpu,memory.used,power.draw,temperature.gpu,clocks.sm,clocks.mem --format=csv -l 1`, Nsight Systems/Compute cho CUDA kernels và Nsight/CUPTI cho copy/bandwidth; Intel dùng RAPL cho CPU package/DRAM; wattmeter/PDU đo AC wall power. Jetson dùng `tegrastats` vì NVIDIA nêu `nvidia-smi` không có trong L4T; chọn và log `nvpmodel`. [Jetson tegrastats/nvpmodel](https://docs.nvidia.com/jetson/agx-orin-devkit/user-guide/howto.html)

## 4. Phương pháp luận sizing và công thức

Đặt `h = 0.25..0.35`; báo cáo dùng bảo thủ `h=0.35`. Lấy **max của ba lần P99/peak hội tụ đã ổn định**, không lấy trung bình.

| Đại lượng đo | Công thức yêu cầu phần cứng | Cách dùng trong PO |
|---|---|---|
| VRAM peak `V_peak` | `V_required = V_peak × (1+h)` | Card chỉ hợp lệ nếu VRAM usable >= `V_required`; reserve thêm framebuffer/compositor nếu không nằm trong trace. |
| RAM peak `R_peak` | `R_required = R_peak × (1+h)` | x86: RAM hệ thống độc lập VRAM; Jetson/DGX UMA: áp dụng cho **tổng** CPU+GPU, không cộng đôi. |
| GPU bandwidth peak `B_peak` | `B_required = B_peak × (1+h)` | So với measured `dram__throughput`/`nvidia-smi`/Nsight, không lấy nominal bandwidth làm FPS. |
| CUDA kernel critical path `T_kernel,p99` | `T_budget = SLA_frame - T_capture - T_decode - T_queue - T_render` | Pass nếu total P99, không chỉ individual kernel, <= budget. |
| GPU/CPU power | `P_design >= P_peak × (1+h)` ở mức DC; PSU cấp hệ thống theo tổng component và inrush | Không sizing theo TDP card đơn lẻ. |
| nhiệt | `Rθ_system <= (Tj_limit - T_ambient,max) / P_peak` | Đo actual Tj/clock 8–24 h; TDP không là bảo chứng nhiệt. |

Dung lượng usable theo headroom 35% của shortlist: 8 GB → 5.93 GB; 16 GB → 11.85 GB; 20 GB → 14.81 GB; 24 GB → 17.78 GB; 32 GB → 23.70 GB; 64 GB → 47.41 GB; 128 GB → 94.81 GB. Điều này là bộ lọc capacity trước benchmark, không phải ước lượng usage.

## 5. Ma trận kỹ thuật đối đầu

`TOPS/TFLOPS` có precision/sparsity khác nhau giữa hãng; không xếp hạng ngang hàng chỉ bằng một cột TOPS. "—" nghĩa là không có một số liệu hãng trực tiếp phù hợp, không tự suy diễn.

| Phân khúc / thiết bị | Bộ nhớ thực dụng | BW công bố | AI compute công bố | Điện/nhiệt & cơ khí | Linux, CUDA/TRT/ORT | Phù hợp OpenJarvis |
|---|---|---:|---:|---|---|---|
| **Jetson Orin Nano Super 8 GB** | 8 GB LPDDR5 dùng chung CPU/GPU | 102 GB/s | 67 sparse INT8 TOPS; 17 FP16 TFLOPS | 7/15/25 W; dev kit 100×79×21 mm | JetPack/Ubuntu; CUDA/TRT; ORT JetPack | **Loại** kiosk đầy đủ do ceiling 5.93 GB; chỉ POC vision nhỏ. [NVIDIA Super Mode](https://developer.nvidia.com/blog/?p=93942) |
| **Jetson Orin NX 16 GB** | 16 GB LPDDR5 UMA | 102 GB/s ở Super Mode | tới 157 sparse INT8 TOPS (vendor figure) | 10–40 W (NX16 Super modes) | Như trên; cần ARM64 wheel audit | Candidate vision-first. 11.85 GB safe ceiling; không mặc định chạy LLM + Metric3D + voice. [JetPack 5.1.5](https://developer.nvidia.com/embedded/jetpack-sdk-515) [Jetson modules](https://developer.nvidia.com/embedded/jetson-modules) |
| **RTX 2000 Ada** | 16 GB GDDR6 ECC dedicated | 288 GB/s (datasheet/vendor claim; xác nhận lại PN trước PO) | 191.9 FP8 Tensor TFLOPS | 70 W active; 2.7×6.6 in dual-slot, PCIe 4 x8 | Ubuntu x86 NVIDIA driver + CUDA/TRT/ORT | Entry SFF. 11.85 GB safe ceiling; tốt nhiệt nhưng chưa dư cho local LLM. [NVIDIA RTX 2000 Ada](https://www.nvidia.com/en-us/products/workstations/rtx-2000/) |
| **RTX 4060 Ti 16 GB** | 16 GB GDDR6 dedicated, non-ECC | NVIDIA công bố 128-bit bus, không nêu BW trực tiếp ở trang spec được dùng | 353 AI TOPS (theoretical) | 165/160 W TGP tùy model; 2-slot reference, PSU 550 W | x86 CUDA/TRT/ORT | Chỉ budget desktop, không ưu tiên: VRAM ceiling bằng RTX 2000 nhưng điện/nhiệt cao hơn, không ECC. [NVIDIA RTX 4060 Ti](https://www.nvidia.com/en-us/geforce/graphics-cards/40-series/rtx-4060-4060ti/) |
| **RTX 4000 SFF Ada** | 20 GB GDDR6 ECC dedicated | 280 GB/s | 686 AI TOPS (marketing precision cần đối chiếu workload) | 70 W active; 2.7×6.6 in dual-slot | x86 CUDA/TRT/ORT | Good legacy shortlist; 14.81 GB ceiling. [NVIDIA datasheet](https://www.nvidia.com/content/dam/en-zz/Solutions/products/workstations/nvidia-rtx-4000-sff-datasheet.pdf) |
| **RTX PRO 4000 Blackwell SFF** | **24 GB GDDR7 ECC** dedicated | **432 GB/s** | **770 AI TOPS** | **70 W active; 2.7×6.6 in dual-slot** | x86 CUDA/TRT/ORT; driver qualification required | **Khuyến nghị kiosk mặc định**; 17.78 GB ceiling, VRAM/ECC tăng mà không tăng thermal design so với 4000 SFF Ada. [NVIDIA product+datasheet](https://www.nvidia.com/en-us/products/workstations/professional-desktop-gpus/rtx-pro-4000-sff/) |
| **Jetson AGX Orin 64 GB** | 64 GB LPDDR5 UMA | 204.8 GB/s | 275 sparse INT8 TOPS | 15–60 W; module 100×87 mm | JetPack/Ubuntu, CUDA/TRT/ORT | Strong embedded alternative if ARM64 is validated; 47.41 GB ceiling. [NVIDIA AGX guide](https://developer.nvidia.com/sites/default/files/akamai/Jetson_AGX_Orin_Developer_Kit_RG_0.pdf) |
| **Jetson AGX Orin Industrial 64 GB** | 64 GB LPDDR5 UMA + inline ECC | 204.8 GB/s | 248 TOPS | 15–75 W; -40 đến 85 °C TTP, lifecycle 10 y | JetPack; use production carrier/cooling | Chọn khi enclosure/DC/MIPI/lifecycle quan trọng hơn x86 portability. [NVIDIA Industrial](https://developer.nvidia.com/blog/step-into-the-future-of-industrial-grade-edge-ai-with-nvidia-jetson-agx-orin-industrial/) |
| **DGX Spark** | 128 GB LPDDR5x UMA | 273 GB/s | tới 1 PFLOP FP4 / 1,000 TOPS | GB10 TDP 140 W, nguồn 240 W; 150×150×50.5 mm | DGX OS/Ubuntu 24.04 ARM64 + CUDA | Dev/LLM appliance, not default kiosk: need USB camera and acoustic test, no proven MIPI carrier path. [hardware](https://docs.nvidia.com/dgx/dgx-spark/hardware.html) [porting](https://docs.nvidia.com/dgx/dgx-spark-porting-guide/overview.html) |

Ghi chú về AGX 32 GB: 200 sparse TOPS, 204.8 GB/s, 15–40 W, 100×87 mm và ceiling 23.70 GB; dùng khi peak measurement chứng minh đủ, nhưng 64 GB giảm đáng kể rủi ro UMA/LLM. [AGX Orin datasheet qua Mouser](https://www.mouser.com/pdfDocs/Jetson_AGX_Orin_DS-10662-001_v12.pdf)

## 6. Giá, tồn kho, lead time và TCO 3 năm

### 6.1 Mốc giá công khai và quy tắc đặt hàng

| Hạng mục | Giá công khai xác minh | Stock/lead time quan sát | Trạng thái để mua |
|---|---:|---|---|
| Jetson Orin Nano Super dev kit | USD 399 MSRP hiện hành | Không dùng stock public làm cam kết | Chỉ dev/POC; không sản xuất. [NVIDIA FAQ](https://developer.nvidia.com/embedded/faq) |
| Jetson Orin NX 16 GB module | USD 999 tại 1,000+ | Findchips aggregate cho PN `900-13767-0000-001` báo tồn kho và **12 tuần**; Newark có listing SKU khác báo **105 tuần** standard lead time | Mâu thuẫn lớn: bắt buộc RFQ; mua module + carrier + heatsink như một BOM. [NVIDIA FAQ](https://developer.nvidia.com/embedded/faq) [Findchips](https://www.findchips.com/search/900-13767-) [Newark listing](https://www.newark.com/nvidia/900-13767-0000-000/jetson-orin-nx-module-16gb-arm/dp/76AK0460) |
| Jetson AGX Orin 64 GB module | USD 2,999 tại 1,000+ | Một distributor aggregate từng thấy 2 pcs ở Mouser; không phải bảo đảm hiện tại | RFQ theo country-of-origin/region và carrier. [NVIDIA FAQ](https://developer.nvidia.com/embedded/faq) [TrustedParts aggregate](https://www.trustedparts.com/en/part/adlink-technology/JETSON%20AGX%20ORIN%2064GB%20MADE%20IN%20USA) |
| Jetson AGX Orin Industrial | USD 3,199 tại 1,000+ | Không có public authorized quote đủ tin cậy trong khảo sát | RFQ chính hãng bắt buộc. [NVIDIA FAQ](https://developer.nvidia.com/embedded/faq) |
| DGX Spark | USD 4,699 MSRP sau thay đổi giá 02-2026 | SKU/region dependent | RFQ NVIDIA partner; không coi giá web cũ USD 3,999 là hiện hành. [NVIDIA price announcement](https://forums.developer.nvidia.com/t/2-23-2026-price-change-announcement/361713) |
| RTX PRO 4000 Blackwell SFF / workstation | NVIDIA công bố spec, không công bố MSRP cố định trên product page | phụ thuộc OEM/partner, không có quote công khai đủ kiểm chứng | RFQ nguyên máy từ Dell/HP/Lenovo hoặc NVIDIA RTX partner, có SLA thay thế. [NVIDIA marketplace](https://marketplace.nvidia.com/en-us/enterprise/laptops-workstations/) |

Không đưa “đơn giá chính xác tại Việt Nam” giả định vào PO: các web store thay đổi theo login/region, và lead time đối nghịch 12 vs 105 tuần đã chứng minh snapshot công khai không có giá trị hợp đồng. Procurement phải lưu PDF quote có: PN, serial/COO, Incoterm, MOQ, lead-time commit, warranty/RMA, carrier, heatsink, PSU và VAT.

### 6.2 TCO năng lượng 3 năm

Không có wattmeter wall-power của chassis OpenJarvis nên chưa thể tuyên bố TCO chính xác. Công thức cần dùng với lịch vận hành thực tế:

`E_3y(kWh) = 3 × 365 × (P_idle × H_idle + P_load × H_load) / 1000`

`TCO_3y = CapEx + E_3y × tariff + warranty/RMA + installation + downtime_spares`.

Ví dụ **trần accelerator/module-only** chạy 24/7 ở công suất công bố, $0.15/kWh, không gồm CPU/chassis/display/cooling: Orin Nano 25 W = $98.55; NX 40 W = $157.68; AGX 64 60 W = $236.52; AGX Industrial 75 W = $295.65; RTX SFF 70 W = $275.94; DGX Spark supply 240 W = $946.08. Đây không phải TCO thực tế; wall-power cần đo theo MLPerf-style hoặc workload thực, vì MLPerf power dùng AC average của **toàn hệ thống tại ổ cắm**. [MLPerf Edge methodology](https://mlcommons.org/benchmarks/inference-edge/)

## 7. Ngoại vi và kiểm thử trước PO

| Hạng mục | Điều phải kiểm chứng | Bằng chứng/ý nghĩa |
|---|---|---|
| Camera USB | Camera đúng model chạy UVC ở số lượng, resolution/FPS mục tiêu qua hub/cáp cuối cùng; đo dropped frame và USB topology | Orin Nano dev carrier có 4 USB 3.2 10 Gbps nhưng production carrier có thể khác. [NVIDIA Nano layout](https://docs.nvidia.com/jetson/orin-nano-devkit/user-guide/latest/hardware_layout.html) |
| Camera MIPI | số lane, connector, cable length, driver sensor, simultaneous cameras và ISP | Nano dev kit có 2 connector 22-pin; AGX carrier có camera connector, nhưng dev board **không** là BOM production. [Nano](https://docs.nvidia.com/jetson/orin-nano-devkit/user-guide/latest/hardware_layout.html) [AGX](https://docs.nvidia.com/jetson/agx-orin-devkit/user-guide/hardware_layout.html) |
| USB/ethernet | đồng thời webcam, audio USB, SSD, network; verify Gen2 10 Gbps per actual carrier, không cộng băng thông lý thuyết | AGX dev kit có Type-A/Type-C Gen2 10 Gbps và 10GbE, nhưng lane topology/carrier cần xác nhận. [AGX ports](https://docs.nvidia.com/jetson/agx-orin-devkit/user-guide/howto.html) |
| Audio | ALSA/PipeWire device, capture-to-playback round-trip P95, drift, XRUN 8 h, mic AEC/noise floor | HDA/USB audio là device/carrier dependent; VieNeu/WebRTC cần chứng minh tại seam thật, không chỉ unit test. [Jetson audio](https://docs.nvidia.com/jetson/archives/r35.5.0/DeveloperGuide/SD/Communications/AudioSetupAndDevelopment.html) |
| Nguồn DC/PSU | voltage/current, connector, PD profile, peak/inrush, UPS hold-up, cable gauge | AGX dev kit PD accepts 20 V 4.5 A và các profile khác; production carrier có yêu cầu khác. [AGX power](https://docs.nvidia.com/jetson/agx-orin-devkit/user-guide/howto.html) |
| Tản nhiệt/ồn | đo dBA A-weighted tại 1 m, ambient 30–35°C, 8 h/24 h, frequency/tonality fan | Không có datasheet GPU/module nào thay được số dBA của chassis cuối. Đặt acceptance: không throttle; P95 <= 35 dBA ở vị trí người dùng (mục tiêu, cần PO xác nhận). |
| Storage/RAM | NVMe endurance/TBW, SMART temp, RAM ECC nếu option, power-loss behavior | Metric3D cache/logs và trace soak sẽ stress SSD; có ảnh hưởng reliability hơn TOPS. |

## 8. Benchmark đối chiếu và giới hạn diễn giải

MLPerf Edge chuẩn hóa scenario/latency/throughput, nêu rõ division Closed để so sánh cùng model và power measurement là AC average toàn hệ thống. Nó là nguồn tốt để kiểm tra vendor claim và quy trình đo nhưng không có benchmark SCRFD + MiniFASNet + Metric3D + WebRTC/VieNeu đúng OpenJarvis. [MLPerf Edge](https://mlcommons.org/benchmarks/inference-edge/)  
Do đó procurement acceptance bắt buộc benchmark OpenJarvis phần 3, đồng thời có thể chạy MLPerf Retinanet/YOLO hoặc GPT-J để so sánh regression giữa hai thiết bị. MLPerf hiện hỗ trợ benchmark vision ONNX và cấu hình GPU `orin`/RTX trong tài liệu GPT-J. [MLPerf benchmark list](https://docs.mlcommons.org/inference/index_gh/) [GPT-J configuration](https://docs.mlcommons.org/inference/benchmarks/language/gpt-j/)

## 9. BOM mẫu và tiêu chí phê duyệt

### BOM-A — kiosk chuẩn (khuyến nghị)

1. x86 SFF workstation Ubuntu 24.04 LTS, CPU 8P-core/16 thread hoặc hơn; 64 GB DDR5; 2 TB NVMe enterprise/TLC; dual 1/2.5GbE tối thiểu.
2. NVIDIA RTX PRO 4000 Blackwell SFF 24 GB ECC 70 W; chassis certified đủ 2-slot low-profile, luồng gió thẳng qua card; PSU tối thiểu 550 W có 30% headroom hệ thống.
3. Camera UVC/MIPI-to-USB đã pass 8h, USB audio interface/mic/speaker đã pass loopback, UPS, telemetry wall-meter.
4. 1 spare mỗi 10 kiosk cho GPU/system theo SLA RMA đã báo giá.

**Gate:** `V_peak <= 17.78 GB`, system RAM peak <= `64/1.35 = 47.41 GB`, mọi P99 latency đạt SLA sản phẩm, no thermal throttle 24h, không XRUN/dropped-frame vượt ngưỡng, P95 noise <= 35 dBA tại 1m (hoặc ngưỡng site được duyệt).

### BOM-B — embedded industrial

1. Jetson AGX Orin Industrial 64 GB, production carrier có CSI/USB/ethernet cần thiết, heatsink/fan/enclosure đã thermal qualify, PSU DC theo carrier.
2. NVMe industrial 1–2 TB; UPS DC; 1 module/carrier spare mỗi 10 kiosk.
3. JetPack version locked; build ARM64 của OpenJarvis, ONNX Runtime CUDA/TensorRT EP, VieNeu ONNX và dependencies đã smoke/soak.

**Gate:** peak UMA <= 47.41 GB, thermal TTP đúng enclosure, all drivers/camera/audio pass. Không dùng dev kit làm BOM.

### BOM-C — NX 16 GB vision-first

Chỉ phê duyệt khi Architect ký rõ Agent/LLM không resident local và peak UMA <= 11.85 GB. Đây là lựa chọn tiết kiệm điện/DC, không phải lối tắt cho full stack.

## 10. Self-critique, kiểm tra bổ sung và các khoảng trống còn lại

Tự rà soát ban đầu phát hiện ba khoảng trống: (a) số liệu stack chỉ 30 giây và VRAM là toàn GPU, (b) stock/lead time Jetson mâu thuẫn mạnh, (c) NVIDIA không công bố dBA của chassis/SFF workstation cũng như MSRP public cố định cho RTX PRO 4000 SFF. Sau đó đã đối chiếu thêm với tài liệu NVIDIA carrier/ports, MLPerf power methodology, FAQ pricing/lifecycle và hai nguồn phân phối/aggregate. Kết quả là các điểm sau **vẫn không được nâng thành fact procurement**:

| Khoảng trống | Tác động | Cách đóng trước PO |
|---|---|---|
| `V_peak`, CUDA critical path, H2D/D2H BW, ambient thermal của workload hội tụ chưa đo | Không thể chứng minh Nano/NX/16GB/20GB đủ | Chạy gate phần 3 trên candidate trong 24h và lưu raw trace. |
| Giá, stock, lead time theo Việt Nam chưa có quote pháp lý | Không thể có “đơn giá chính xác” trong report | RFQ ít nhất 2 đại lý uỷ quyền, cùng PN/Incoterm/MOQ, hiệu lực >=14 ngày. |
| Noise của chassis cuối | Rủi ro không gian công cộng yên tĩnh | Mượn/evaluate unit trong enclosure cuối, dBA/tonality 1m, 8h. |
| ONNX Runtime Jetson compatibility là version matrix, không phải auto-pass | Có thể fallback CPU hoặc build wheel thiếu provider | Lock JetPack/CUDA/TRT/ORT, CI check providers và trace GPU kernels. |
| TOPS sparse/FP4/FP8 không đồng nhất | So sánh marketing sai | Chỉ dùng TOPS làm filter; quyết định theo OpenJarvis P99 + wall power. |

### Kết luận cuối

Với dữ liệu hiện có, **BOM-A (x86 SFF + RTX PRO 4000 Blackwell SFF 24 GB ECC)** là lựa chọn phù hợp nhất cho triển khai kiosk đầy đủ: 24 GB VRAM dedicated/ECC, 432 GB/s và 70 W giảm rủi ro VRAM/nhiệt hơn các lựa chọn 16 GB mà không đẩy kiosk thành workstation lớn. **AGX Orin Industrial 64 GB** là lựa chọn đúng khi yêu cầu embedded, DC, MIPI và lifecycle 10 năm quan trọng hơn chi phí/portability x86. **Orin NX 16 GB** chỉ dành cho vision-first sau khi benchmark chứng minh giới hạn 11.85 GB UMA. Không phê duyệt Orin Nano 8 GB cho full stack.
