from pathlib import Path

from setuptools import setup


ROOT = Path(__file__).parent
SKILL_ROOT = ROOT / "skills" / "recipe-nourishible"


def skill_data_files():
    groups = {}
    for path in SKILL_ROOT.rglob("*"):
        if not path.is_file() or "__pycache__" in path.parts:
            continue
        relative_parent = path.parent.relative_to(SKILL_ROOT)
        destination = Path("share/nourishible/recipe-nourishible") / relative_parent
        groups.setdefault(str(destination), []).append(str(path.relative_to(ROOT)))
    return sorted(groups.items())


setup(data_files=skill_data_files())
