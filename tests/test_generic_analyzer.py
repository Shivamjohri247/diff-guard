from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from diff_guard.analyzers.generic_analyzer import GenericAnalyzer


# ======================================================================
# Sample source code used across tests
# ======================================================================

GO_SOURCE = """\
package main

import "fmt"
import f "fmt"
import (
\t"os"
\t"strings"
)

func main() {
\tfmt.Println("hello")
}

func (s *Server) handleRequest() {
}
"""

RUST_SOURCE = """\
use std::collections::HashMap;
use crate::models::User;
extern crate serde;

fn main() {
\tlet mut map = HashMap::new();
}

pub fn create_user(name: &str) -> User {
\tUser { name: name.to_string() }
}
"""

JAVA_SOURCE = """\
package com.example;

import java.util.List;
import static org.junit.Assert.assertEquals;

public class UserService {
    public void addUser(String name) {
    }

    private static String formatName(String name) {
        return name;
    }
}
"""

RUBY_SOURCE = """\
require "json"
require_relative "models/user"
include ActiveModel::Serialization

def initialize(name)
  @name = name
end

def full_name
  "#{@name}"
end
"""

JS_SOURCE = """\
import React from 'react';
import { useState } from 'react';
const express = require('express');
export { something } from './utils';

function App() {
  return null;
}

const handler = (req, res) => {
  res.send('ok');
};

const helper = () => 42;
"""

PYTHON_SOURCE = """\
import os
from pathlib import Path
from collections import defaultdict

def main():
    pass

async def fetch():
    pass
"""

C_SOURCE = """\
#include <stdio.h>
#include "myheader.h"

int main() {
    printf("hello");
    return 0;
}
"""


# ======================================================================
# Tests
# ======================================================================


class TestExtractGoImports:
    def test_extract_go_imports(self) -> None:
        analyzer = GenericAnalyzer()
        imports = analyzer.extract_imports(GO_SOURCE, "main.go")
        assert "fmt" in imports
        assert "os" in imports
        assert "strings" in imports


class TestExtractRustImports:
    def test_extract_rust_imports(self) -> None:
        analyzer = GenericAnalyzer()
        imports = analyzer.extract_imports(RUST_SOURCE, "main.rs")
        assert "std::collections::HashMap" in imports
        assert "crate::models::User" in imports
        assert "serde" in imports


class TestExtractJavaImports:
    def test_extract_java_imports(self) -> None:
        analyzer = GenericAnalyzer()
        imports = analyzer.extract_imports(JAVA_SOURCE, "UserService.java")
        assert "java.util.List" in imports
        assert "org.junit.Assert.assertEquals" in imports


class TestExtractRubyImports:
    def test_extract_ruby_imports(self) -> None:
        analyzer = GenericAnalyzer()
        imports = analyzer.extract_imports(RUBY_SOURCE, "user.rb")
        assert "json" in imports
        assert "models/user" in imports
        assert "ActiveModel::Serialization" in imports


class TestExtractJSImports:
    def test_extract_js_imports(self) -> None:
        analyzer = GenericAnalyzer()
        imports = analyzer.extract_imports(JS_SOURCE, "app.js")
        assert "react" in imports
        assert "express" in imports
        assert "./utils" in imports


class TestExtractPythonImports:
    def test_extract_python_imports(self) -> None:
        analyzer = GenericAnalyzer()
        imports = analyzer.extract_imports(PYTHON_SOURCE, "main.py")
        assert "os" in imports
        assert "pathlib" in imports
        assert "collections" in imports


class TestExtractGoFunctions:
    def test_extract_go_functions(self) -> None:
        analyzer = GenericAnalyzer()
        funcs = analyzer.extract_functions(GO_SOURCE)
        names = [name for name, _, _ in funcs]
        assert "main" in names
        assert "handleRequest" in names


class TestExtractRustFunctions:
    def test_extract_rust_functions(self) -> None:
        analyzer = GenericAnalyzer()
        funcs = analyzer.extract_functions(RUST_SOURCE)
        names = [name for name, _, _ in funcs]
        assert "main" in names
        assert "create_user" in names


class TestExtractJSFunctions:
    def test_extract_js_functions(self) -> None:
        analyzer = GenericAnalyzer()
        funcs = analyzer.extract_functions(JS_SOURCE)
        names = [name for name, _, _ in funcs]
        assert "App" in names
        assert "handler" in names
        assert "helper" in names


class TestExtractRubyFunctions:
    def test_extract_ruby_functions(self) -> None:
        analyzer = GenericAnalyzer()
        funcs = analyzer.extract_functions(RUBY_SOURCE)
        names = [name for name, _, _ in funcs]
        assert "initialize" in names
        assert "full_name" in names


class TestExtractCImports:
    def test_extract_c_imports(self) -> None:
        analyzer = GenericAnalyzer()
        imports = analyzer.extract_imports(C_SOURCE, "main.c")
        assert "stdio.h" in imports
        assert "myheader.h" in imports


class TestExtractJavaFunctions:
    def test_extract_java_functions(self) -> None:
        analyzer = GenericAnalyzer()
        funcs = analyzer.extract_functions(JAVA_SOURCE)
        names = [name for name, _, _ in funcs]
        assert "addUser" in names
        assert "formatName" in names


class TestFindReferences:
    def test_find_references(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "src").mkdir()
            (root / "src" / "main.py").write_text("def my_func(): pass\n")
            (root / "src" / "other.py").write_text("from main import my_func\n")
            (root / "src" / "unrelated.py").write_text("print('hello')\n")

            analyzer = GenericAnalyzer()
            refs = analyzer.find_references("my_func", root)
            assert "src/main.py" in refs
            assert "src/other.py" in refs
            assert "src/unrelated.py" not in refs

    def test_find_references_excludes_binary(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "code.py").write_text("my_func()\n")
            binary_path = root / "data.bin"
            binary_path.write_bytes(b"\x00\x01\x02\x03my_func\xFF\xFE")

            analyzer = GenericAnalyzer()
            refs = analyzer.find_references("my_func", root)
            assert "code.py" in refs
            assert "data.bin" not in refs

    def test_find_references_excludes_skip_dirs(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "src").mkdir()
            (root / "src" / "main.py").write_text("target_func()\n")
            (root / "node_modules").mkdir()
            (root / "node_modules" / "lib.js").write_text("target_func()\n")
            (root / ".git").mkdir()
            (root / ".git" / "HEAD").write_text("target_func\n")

            analyzer = GenericAnalyzer()
            refs = analyzer.find_references("target_func", root)
            assert "src/main.py" in refs
            assert "node_modules/lib.js" not in refs
            assert ".git/HEAD" not in refs


class TestFallbackForUnknown:
    def test_fallback_for_unknown(self) -> None:
        analyzer = GenericAnalyzer()
        source = "import something\nfrom other import thing\n"
        imports = analyzer.extract_imports(source, "file.xyz")
        # Should still pick up generic patterns
        assert "something" in imports
        assert "other" in imports


class TestEmptySource:
    def test_empty_source(self) -> None:
        analyzer = GenericAnalyzer()
        assert analyzer.extract_imports("", "main.go") == []
        assert analyzer.extract_functions("") == []
        assert analyzer.extract_classes("") == []
        assert analyzer.extract_calls("") == []
        assert analyzer.line_to_function("", [1]) == []


class TestMultilineGoImports:
    def test_multiline_go_imports(self) -> None:
        analyzer = GenericAnalyzer()
        source = """\
package main

import (
\t"fmt"
\t"os"
)

func main() {}
"""
        imports = analyzer.extract_imports(source, "main.go")
        assert "fmt" in imports
        assert "os" in imports
