from src.common.cleanup import clean_python_caches


def test_clean_python_caches_removes_pycache_directories(tmp_path) -> None:
    cache_dir = tmp_path / "src" / "common" / "__pycache__"
    cache_dir.mkdir(parents=True)
    (cache_dir / "module.cpython-312.pyc").write_bytes(b"cache")

    removed_paths = clean_python_caches(tmp_path)

    assert removed_paths == [cache_dir]
    assert not cache_dir.exists()
