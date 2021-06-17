"""
The MIT License (MIT)

Copyright (c) 2019-current IAmTomahawkx

Permission is hereby granted, free of charge, to any person obtaining a
copy of this software and associated documentation files (the "Software"),
to deal in the Software without restriction, including without limitation
the rights to use, copy, modify, merge, publish, distribute, sublicense,
and/or sell copies of the Software, and to permit persons to whom the
Software is furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in
all copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS
OR IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING
FROM, OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER
DEALINGS IN THE SOFTWARE.
"""


class Adapter(object):
    def __init__(self, brackets=(("(", ")"),), delimiters=(",",)):
        self._original_brackets = brackets
        self._brackets = dict(brackets)
        self.brackets_in = set([b[0] for b in brackets])
        self.brackets_out = set([b[1] for b in brackets])
        self.delimiters = set(delimiters)

    def parse(self, buffer, maxdepth=0):
        return self._actual_parse(buffer, 0, maxdepth)

    def _actual_parse(self, buffer, depth, maxdepth):
        collecting = False
        params = [""]
        bracketlvl = 0
        for index, char in enumerate(buffer):
            if isinstance(params[-1], dict):
                params[-1]["raw"] += char

            if char == "$" and bracketlvl == 0:
                brack = False
                for c in buffer[index + 1 :]:
                    if not c.isalnum():
                        if c in self.brackets_in:
                            brack = True
                        break

                if not brack:
                    # there are no brackets, just append and go to the next iteration
                    del brack
                    if isinstance(params[-1], dict):
                        params[-1]["params"][-1] += char
                    else:
                        params[-1] += char
                    continue

                params.append({"name": "", "params": [""], "raw": "$"})
                collecting = True  # enable name collection
                continue

            if char in self.brackets_in and buffer[index - 1] != "\\":
                collecting = False
                bracketlvl += 1
                if (
                    bracketlvl <= 1
                ):  # if its smaller than one, we need to remove it so it doesnt appear in the first argument.
                    continue

            if collecting:
                # we are collecting a parameter name here, so append to the name, and go to the next iteration.
                params[-1]["name"] += char
                continue

            if char in self.brackets_out and buffer[index - 1] != "\\":
                bracketlvl = max(bracketlvl - 1, 0)
                if bracketlvl == 0:
                    if isinstance(params[-1], dict):
                        if not params[-1]["params"][-1].strip():
                            params[-1]["params"].pop()
                    params.append("")
                    continue  # if it is, im going to continue, as to not add the bracket to the outer layer.

            if char in self.delimiters and bracketlvl <= 1 and buffer[index - 1] != "\\":
                # if we are here, this means that weve hit a delimiter.
                params[-1]["params"][-1] = params[-1]["params"][-1].strip()
                params[-1]["params"].append("")
                continue

            if isinstance(params[-1], dict):
                params[-1]["params"][-1] += char
            else:
                params[-1] += char

        for item in params:
            if isinstance(item, dict) and not (depth + 1 >= maxdepth):
                for index, param in enumerate(item["params"]):
                    item["params"][index] = self._actual_parse(param, depth + 1, maxdepth)

        if depth == 0:
            return params

        if len(params) == 1:
            return params[0]

        return params

    def copy(self):
        return Adapter(self._original_brackets, self.delimiters)


def split(string: str):
    ret = [""]
    collect = False
    for char in string:
        if char == "-" and ret[-1] != "-":
            collect = True
            ret.append("-")
            continue
        if char.isspace() and collect:
            collect = False
            ret.append("")
            continue
        ret[-1] += char

    # noinspection PyBroadException
    try:
        ret.remove("")
    except:
        pass
    return ret
