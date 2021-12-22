from typing import List

class Token:
    name: str
    value: str
    start: int
    end: int

def run_lex(input: str) -> List[Token]: ...
