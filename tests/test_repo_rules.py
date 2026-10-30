"""AC-14: one code path for every OS."""
import re
import subprocess

from conftest import ROOT


def tracked_and_new():
    out = subprocess.run(["git", "ls-files", "--cached", "--others", "--exclude-standard"], cwd=ROOT, capture_output=True, text=True).stdout
    return [l for l in out.splitlines() if l and not l.startswith((".claude/", ".agents/"))]


def test_no_os_specific_scripts_or_wrapper():
    bad = [f for f in tracked_and_new() if re.search(r"\.(sh|ps1|bat|cmd)$|(^|/)gradlew(\.bat)?$|gradle-wrapper", f)]
    assert bad == []


def test_no_os_branches_in_harness():
    src = "\n".join(p.read_text(encoding="utf-8") for p in (ROOT / "chaos").glob("*.py"))
    assert not re.search(r"sys\.platform|os\.name|platform\.system|import platform\b", src)


def test_git_rules():
    attrs = (ROOT / ".gitattributes").read_text()
    assert re.search(r"^\* text=auto eol=lf$", attrs, re.M)
    assert re.search(r"^results/\*\* -text$", attrs, re.M)
    assert re.search(r"^reports/$", (ROOT / ".gitignore").read_text(), re.M)
