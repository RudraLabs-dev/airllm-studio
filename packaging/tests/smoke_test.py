"""Smoke test run against every built payload and every installed package.

    airllm-python smoke_test.py --expect-version 4.0.0

Checks that the bundled interpreter can import the full stack, that the installed airllm is
the version we meant to ship, and that torch can actually compute. It does not download a model.
"""
import argparse
import importlib.metadata as md
import platform
import sys
import warnings


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--expect-version", help="airllm version that must be installed")
    args = parser.parse_args()

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        import airllm  # noqa: F401
        from airllm import AutoModel  # noqa: F401  # the public entry point must exist
        import PIL
        import torch
        import torchvision        # image processors of vision-language models
        import transformers

    optional = [str(w.message) for w in caught if "optional model class" in str(w.message)]

    report = {
        "python": platform.python_version(),
        "platform": platform.platform(),
        "executable": sys.executable,
        "airllm": md.version("airllm"),
        "airllm_path": airllm.__file__,
        "torch": torch.__version__,
        "torch_cuda": torch.version.cuda or "cpu",
        "transformers": transformers.__version__,
        "torchvision": torchvision.__version__,
        "pillow": PIL.__version__,
    }
    for key, value in report.items():
        print(f"{key:>14}: {value}")
    for msg in optional:
        print(f"{'note':>14}: {msg}")

    if args.expect_version and report["airllm"] != args.expect_version:
        print(f"FAIL: expected airllm {args.expect_version}, got {report['airllm']}", file=sys.stderr)
        return 1

    x = torch.arange(6, dtype=torch.float32).reshape(2, 3)
    if float((x @ x.T).sum()) != 83.0:  # [[5, 14], [14, 50]]
        print("FAIL: torch matmul returned a wrong result", file=sys.stderr)
        return 1

    print("SMOKE TEST PASSED")
    return 0


if __name__ == "__main__":
    sys.exit(main())
