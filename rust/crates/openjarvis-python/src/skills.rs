//! PyO3 bindings for skill manifests and verification.

use pyo3::prelude::*;

#[pyclass(name = "SkillManifest")]
pub struct PySkillManifest {
    inner: openjarvis_skills::SkillManifest,
}

#[pymethods]
impl PySkillManifest {
    #[getter]
    fn name(&self) -> &str {
        &self.inner.name
    }

    #[getter]
    fn version(&self) -> &str {
        &self.inner.version
    }

    #[getter]
    fn description(&self) -> &str {
        &self.inner.description
    }

    #[getter]
    fn author(&self) -> &str {
        &self.inner.author
    }

    #[getter]
    fn steps_count(&self) -> usize {
        self.inner.steps.len()
    }

    #[getter]
    fn required_capabilities(&self) -> Vec<String> {
        self.inner.required_capabilities.clone()
    }

    fn to_json(&self) -> String {
        serde_json::to_string(&self.inner).unwrap_or_default()
    }

    fn manifest_bytes(&self) -> Vec<u8> {
        self.inner.manifest_bytes()
    }

    fn verify_signature(&self, public_key_hex: &str) -> bool {
        match parse_public_key_hex(public_key_hex) {
            Some(key_bytes) => openjarvis_skills::verify_signature(&self.inner, &key_bytes),
            None => false,
        }
    }
}

fn parse_public_key_hex(public_key_hex: &str) -> Option<Vec<u8>> {
    if !public_key_hex.len().is_multiple_of(2) {
        return None;
    }
    if !public_key_hex.is_ascii() {
        return None;
    }

    let mut key_bytes = Vec::with_capacity(public_key_hex.len() / 2);
    for i in (0..public_key_hex.len()).step_by(2) {
        match u8::from_str_radix(&public_key_hex[i..i + 2], 16) {
            Ok(byte) => key_bytes.push(byte),
            Err(_) => return None,
        }
    }
    Some(key_bytes)
}

#[pyfunction]
pub fn load_skill(toml_str: &str) -> PyResult<PySkillManifest> {
    let manifest = openjarvis_skills::load_skill(toml_str)
        .map_err(|e| PyErr::new::<pyo3::exceptions::PyValueError, _>(e))?;
    Ok(PySkillManifest { inner: manifest })
}

#[cfg(test)]
mod tests {
    use super::parse_public_key_hex;

    #[test]
    fn empty_input_returns_empty_vec() {
        assert_eq!(parse_public_key_hex(""), Some(Vec::new()));
    }

    #[test]
    fn valid_hex_decodes() {
        assert_eq!(
            parse_public_key_hex("0a1b2cFF"),
            Some(vec![0x0a, 0x1b, 0x2c, 0xff])
        );
    }

    #[test]
    fn odd_length_rejected_without_panic() {
        // Regression: the pre-fix implementation sliced public_key_hex[i..i+2]
        // on an odd-length string, triggering an out-of-bounds panic and a
        // DoS vector when the input was attacker-controlled.
        assert_eq!(parse_public_key_hex("0"), None);
        assert_eq!(parse_public_key_hex("abc"), None);
        assert_eq!(parse_public_key_hex("0a1b2"), None);
    }

    #[test]
    fn non_hex_chars_rejected() {
        // Pre-fix `filter_map` silently dropped non-hex chars and produced a
        // truncated key, which would also have caused verification surprises.
        assert_eq!(parse_public_key_hex("zz"), None);
        assert_eq!(parse_public_key_hex("0aZZ"), None);
        assert_eq!(parse_public_key_hex("gh"), None);
    }

    #[test]
    fn multibyte_utf8_rejected_without_panic() {
        // Pre-fix indexing public_key_hex[i..i+2] on a non-ASCII string could
        // split a multi-byte UTF-8 codepoint and panic. The ASCII-only check
        // makes the rejection explicit instead of relying on from_str_radix's
        // post-slice error path.
        assert_eq!(parse_public_key_hex("é"), None);
        assert_eq!(parse_public_key_hex("aaé"), None);
    }
}
