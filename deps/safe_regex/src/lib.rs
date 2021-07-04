use pyo3::{
    create_exception,
    exceptions::PyException,
    prelude::*,
    PyObjectProtocol
};
use regex::{
    Regex,
    Error,
    RegexBuilder
};
use pyo3::types::PyString;

#[pyclass(module="safe_regex")]
#[derive(Debug)]
struct Re {
    _re: Regex
}

impl Re {
    fn new(input: &str) -> Result<Re, Error> {
        let re = RegexBuilder::new(input)
            .multi_line(true)
            .size_limit(4000)
            .dfa_size_limit(4000)
            .build()?;
        Ok(Re { _re: re })
    }
}

#[pyproto]
impl PyObjectProtocol for Re {
    fn __repr__(&self) -> String {
        format!("<Re pattern={}>", self._re.as_str())
    }
}

#[pymethods]
impl Re {
    #[new]
    fn pynew(input: &PyString) -> PyResult<Re> {
        Re::new(input.to_str()?).map_err(|e| CompileError::new_err(e.to_string()))
    }

    #[text_signature = "(input: str)"]
    fn find(&self, input: &str) -> Option<String> {
        let mat = self._re.find(input)?;
        Some(mat.as_str().to_string())
    }

    #[text_signature = "(input: str)"]
    fn is_match(&self, input: &str) -> bool {
        self._re.is_match(input)
    }

    #[text_signature = "(input: str, replacer: str)"]
    fn replace(&self, input: &str, replacer: &str) -> String {
        self._re.replace(input, replacer).to_string()
    }
}

unsafe impl Send for Re {}

create_exception!(safe_regex, CompileError, PyException);

#[pymodule(safe_regex)]
fn module(py: Python, m: &PyModule) -> PyResult<()> {
    m.add_class::<Re>()?;
    m.add("CompileError", py.get_type::<CompileError>())?;

    #[pyfn(m, "compile")]
    #[text_signature = "(input: str)"]
    fn compile(input: &str) -> PyResult<Re> {
        Re::new(input).map_err(|e| CompileError::new_err(e.to_string()))
    }

    Ok(())
}