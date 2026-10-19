import json

import pytest

from airllm_studio import store as store_mod
from airllm_studio.store import Manifest, ModelStore, StoreError, human_count, select_files


def test_select_files_prefers_safetensors_and_skips_subfolders():
    files = [("config.json", 1), ("tokenizer.json", 2), ("model-00001-of-00002.safetensors", 10),
             ("model-00002-of-00002.safetensors", 10), ("model.safetensors.index.json", 1),
             ("pytorch_model-00001-of-00002.bin", 10), ("pytorch_model.bin.index.json", 1),
             ("original/consolidated.00.pth", 99), ("README.md", 1), ("training_args.bin", 1)]
    names = [n for n, _ in select_files(files)]
    assert "original/consolidated.00.pth" not in names and "README.md" not in names
    assert not any(n.endswith(".bin") for n in names)
    assert names[0] == "config.json" and names[-1].endswith(".safetensors")


def test_select_files_falls_back_to_bin_and_rejects_gguf():
    names = [n for n, _ in select_files([("config.json", 1), ("pytorch_model.bin", 5)])]
    assert names == ["config.json", "pytorch_model.bin"]
    with pytest.raises(StoreError, match="GGUF"):
        select_files([("config.json", 1), ("model-q4.gguf", 5)])
    with pytest.raises(StoreError, match="config.json"):
        select_files([("model.safetensors", 5)])


def test_human_count():
    assert human_count(135e6) == "135M" and human_count(7.2e9) == "7.2B" and human_count(6.71e11) == "671B"


def _local_model(tmp_path):
    folder = tmp_path / "my-model"
    folder.mkdir()
    (folder / "config.json").write_text(json.dumps({
        "architectures": ["LlamaForCausalLM"], "model_type": "llama", "num_hidden_layers": 2,
        "max_position_embeddings": 2048, "torch_dtype": "bfloat16"}))
    (folder / "model.safetensors").write_bytes(b"\0" * 4000)
    return folder


def test_local_import_runs_prepare_and_writes_manifest(home, tmp_path, monkeypatch):
    calls = []
    monkeypatch.setattr(store_mod, "split_layers", lambda *a, **k: calls.append(a))

    class TextOnly:
        def set_layer_names_dict(self):
            self.layer_names_dict = {"layer_prefix": "model.layers"}

    monkeypatch.setattr(store_mod, "airllm_class_for", lambda *a, **k: TextOnly)
    st = ModelStore(lambda: tmp_path / "models", lambda: None)
    job = st.pull(str(_local_model(tmp_path)))
    events = list(job.events(timeout=0.1))
    assert events[-1]["phase"] == "success", events[-1]
    m = st.get("local/my-model")
    assert m.status == "ready" and m.source == "local" and m.context_length == 2048
    assert m.parameter_size == "2.0K"          # 4000 bytes of bf16
    assert calls and str(calls[0][0]).endswith("my-model")
    assert m.capabilities == ["completion"]


def test_failed_prepare_is_reported(home, tmp_path, monkeypatch):
    def boom(*a, **k):
        raise OSError(28, "No space left on device")
    monkeypatch.setattr(store_mod, "split_layers", boom)
    st = ModelStore(lambda: tmp_path / "models", lambda: None)
    job = st.pull(str(_local_model(tmp_path)))
    final = list(job.events(timeout=0.1))[-1]
    assert final["phase"] == "error" and "disk space" in final["error"]
    assert st.get("local/my-model").status == "error"


def test_bad_names_and_restart_recovery(tmp_path):
    st = ModelStore(lambda: tmp_path / "models", lambda: None)
    with pytest.raises(StoreError):
        st.pull("not-a-repo-id")
    st.save(Manifest(name="a/b", status="downloading"))
    st2 = ModelStore(lambda: tmp_path / "models", lambda: None)
    assert st2.get("a/b").status == "error" and "Interrupted" in st2.get("a/b").error


def test_delete_removes_files(tmp_path):
    st = ModelStore(lambda: tmp_path / "models", lambda: None)
    layers = tmp_path / "models" / "layers" / "a--b"
    layers.mkdir(parents=True)
    (layers / "x.safetensors").write_bytes(b"1234")
    st.save(Manifest(name="a/b", repo="a/b", status="ready", layers_path=str(layers)))
    assert st.disk_usage(st.get("a/b")) == 4
    st.delete("a/b")
    assert not layers.exists() and st.get("a/b") is None


def test_download_progress_follows_the_downloaders_byte_counts(monkeypatch):
    """With Xet the *.incomplete file stays tiny while data arrives; progress must come from the
    downloader's own bars (here: the 'reconstructing' and 'downloading bytes' bars of one file)."""
    from airllm_studio.store import PullJob, _progress_kwargs

    job = PullJob("org/m")
    monkeypatch.setattr(store_mod.time, "monotonic", iter(range(10, 1000)).__next__)   # every call is 1 s later
    kwargs = _progress_kwargs(job, base=1000, size=500)
    if "tqdm_class" not in kwargs:
        pytest.skip("huggingface-hub without tqdm_class: file-size watcher only")
    bar_cls = kwargs["tqdm_class"]
    disk = bar_cls(desc="f: reconstructing file", total=500, unit="B", disable=True)
    net = bar_cls(desc="f: downloading bytes", total=500, unit="B", disable=True)
    net.update(120)
    assert job.completed == 1120
    disk.update(50)                       # slower bar: the highest count wins, never goes back
    assert job.completed == 1120
    net.update(900)                       # more than the file size: clamped
    assert job.completed == 1500
