use pyo3::{
    create_exception,
    exceptions::PyException,
    prelude::*,
    PyObjectProtocol
};
use logos::{
    Logos,
    Span,
    Source
};

create_exception!(arg_lex, LexError, PyException);

#[derive(Logos, Debug, PartialEq, Clone)]
enum Tokenizer {
    #[regex(r"%[a-zA-Z0-9]+")]
    Counter,

    #[regex(r"\$[a-zA-Z0-9]+")]
    Var,

    #[token("(")]
    PIn,

    #[token(")")]
    POut,

    #[token("==")]
    EQ,

    #[token("!=")]
    NEQ,

    #[token(">=")]
    GEQ,

    #[token("<=")]
    SEQ,

    #[token("<")]
    SQ,

    #[token(">")]
    GQ,

    #[token("||")]
    Or,

    #[token("&&")]
    And,

    #[regex(r"[0-9]+|'(?:\\'|[^'])*'")]
    #[token("\\>")]
    #[token("\\<")]
    #[token("\\<=")]
    #[token("\\>=")]
    #[token("\\!=")]
    #[token("\\==")]
    #[token("\\)")]
    #[token("\\(")]
    #[token("\\||")]
    #[token("\\&&")]
    Literal,

    #[regex(r"[ \t\n\f]+")]
    Whitespace,

    #[token(",")]
    VarSep,

    #[regex(r"/(?:\\/|[^/])*/")]
    Regex,

    #[token("true")]
    #[token("True")]
    #[token("false")]
    #[token("False")]
    Bool,

    #[error]
    ERROR
}

#[pyclass(module="arg_lex")]
#[derive(Debug)]
struct Token {
    #[pyo3(get)]
    name: String,
    #[pyo3(get)]
    value: String,
    #[pyo3(get)]
    start: u32,
    #[pyo3(get)]
    end: u32
}

impl Token {
    fn from_token(input: &str, token: Tokenizer, r: Span) -> Token {
        let name = match token {
            Tokenizer::Counter => "Counter",
            Tokenizer::Var => "Var",
            Tokenizer::PIn => "PIn",
            Tokenizer::POut => "POut",
            Tokenizer::EQ => "EQ",
            Tokenizer::NEQ => "NEQ",
            Tokenizer::GEQ => "GEQ",
            Tokenizer::SEQ => "SEQ",
            Tokenizer::SQ => "SQ",
            Tokenizer::GQ => "GQ",
            Tokenizer::VarSep => "VarSep",
            Tokenizer::Literal => "Literal",
            Tokenizer::Or => "Or",
            Tokenizer::And => "And",
            Tokenizer::Regex => "Regex",
            Tokenizer::Whitespace => "Whitespace",
            Tokenizer::Bool => "Bool",
            Tokenizer::ERROR => "Error"
        }.to_string();
        let start = r.start as u32;
        let end = r.end as u32;
        let value: String = (&input).slice(r).unwrap().to_string();
        Token {
            name,
            value,
            start,
            end
        }
    }
}

#[pyproto]
impl PyObjectProtocol for Token {
    fn __str__(&self) -> String {
        format!("<Token name={} start={} end={} value={}>", self.name, self.start, self.end, self.value)
    }
    fn __repr__(&self) -> String {
        format!("<Token name={} start={} end={} value={}>", self.name, self.start, self.end, self.value)
    }
}

unsafe impl Send for Token {}

#[pymodule(arg_lex)]
fn arglex(py: Python, m: &PyModule)-> PyResult<()> {
    m.add_class::<Token>()?;
    m.add("LexError", py.get_type::<LexError>())?;

    #[pyfn(m, "run_lex")]
    #[text_signature = "(input: str)"]
    fn run_lex(input: String) -> PyResult<Vec<Token>> {
        let lex = Tokenizer::lexer(&input);
        let tokens = lex.spanned()
            .map(|(tok, spn)| Token::from_token(&input.as_str(), tok, spn))
            .collect::<Vec<Token>>();

        Ok(tokens)
    }

    Ok(())
}