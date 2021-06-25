use pyo3::{
    create_exception,
    exceptions::PyException,
    prelude::*
};
use regex::{
    Regex,
    Error,
    RegexBuilder
};

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

#[pymethods]
impl Re {
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
        let re = Re::new(input);
        if let Ok(r) = re {
            Ok(r)
        } else {
            Err(CompileError::new_err(re.err().unwrap().to_string()))
        }
    }

    Ok(())
}