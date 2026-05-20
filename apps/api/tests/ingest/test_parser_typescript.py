from architect.ingest.parsers.typescript import parse_typescript

SAMPLE = b'''
import { helper } from "./sibling";
import React from "react";
import * as utils from "./utils";

export function top(x: number): number {
  return helper(x);
}

export const arrow = async (n: number): Promise<number> => {
  return helper(n) + 1;
};

export class Greeter {
  constructor(private readonly name: string) {}

  async greet(): Promise<string> {
    return `hi ${this.name}`;
  }
}

function callsMethod() {
  const g = new Greeter("nico");
  g.greet();
}
'''


def test_extracts_module_and_definitions() -> None:
    pf = parse_typescript(repo="demo", rel_path="src/mod.ts", source=SAMPLE)
    assert pf.module_qname == "src/mod"
    qnames = {d.qname for d in pf.definitions}
    assert "src/mod::top" in qnames
    assert "src/mod::arrow" in qnames
    assert "src/mod::Greeter" in qnames
    assert "src/mod::Greeter::greet" in qnames
    assert "src/mod::callsMethod" in qnames


def test_extracts_imports() -> None:
    pf = parse_typescript(repo="demo", rel_path="src/mod.ts", source=SAMPLE)
    sources = sorted({imp.source for imp in pf.imports})
    assert "./sibling" in sources
    assert "react" in sources
    assert "./utils" in sources


def test_extracts_calls_inside_arrow_and_method() -> None:
    pf = parse_typescript(repo="demo", rel_path="src/mod.ts", source=SAMPLE)
    callers = {c.caller_qname for c in pf.calls}
    assert "src/mod::top" in callers
    assert "src/mod::arrow" in callers
    assert "src/mod::callsMethod" in callers
