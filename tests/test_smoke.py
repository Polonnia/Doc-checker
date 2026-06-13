from pathlib import Path

from doc_checker.config import load_config


def test_config_loads() -> None:
    cfg = load_config(Path(__file__).resolve().parents[1] / "config.yaml")
    assert cfg.paths.rule_pdf.exists()
    assert cfg.paths.sample_xml_dir.exists()
