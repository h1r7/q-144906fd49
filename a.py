import hashlib, io, os, re, stat, subprocess, sys, zipfile
from pathlib import Path

H = 'a07e2392ecf8eb3caf526dbfbecd8b36ca58bcd0dba3e97403cdbed372e07575'
N = '1630d10aa9342c30d690efa4e1d139ced2e534ce6575e190f282958236d508d2'
C = 42

def unpack():
    blob = (Path(__file__).resolve().parent / "b.dat").read_bytes()
    if len(blob) > 1024 * 1024 or hashlib.sha256(blob).hexdigest() != H:
        raise ValueError("e0")
    with zipfile.ZipFile(io.BytesIO(blob)) as archive:
        entries = archive.infolist()
        names = [entry.filename for entry in entries]
        if len(names) != C or len(set(names)) != C or hashlib.sha256("\n".join(sorted(names)).encode()).hexdigest() != N:
            raise ValueError("e1")
        if sum(entry.file_size for entry in entries) > 1024 * 1024:
            raise ValueError("e2")
        for entry in entries:
            if not re.fullmatch(r"[a-z_-]+\.(py|m|js|txt)", entry.filename) or entry.is_dir() or entry.flag_bits & 1 or stat.S_ISLNK(entry.external_attr >> 16):
                raise ValueError("e3")
        temporary = Path(os.environ["RUNNER_TEMP"]).resolve(strict=True)
        root = temporary / ("q0-" + H[:12])
        if root.is_symlink():
            raise ValueError("e4")
        root.mkdir(mode=0o700, exist_ok=True)
        if root.resolve().parent != temporary:
            raise ValueError("e5")
        for entry in entries:
            target = root / entry.filename
            raw = archive.read(entry)
            if target.is_symlink():
                raise ValueError("e6")
            if target.exists():
                if not target.is_file() or target.read_bytes() != raw:
                    raise ValueError("e7")
            else:
                with target.open("xb") as stream:
                    stream.write(raw)
        return root

def main():
    if len(sys.argv) != 2 or sys.argv[1] not in {"k" + str(i) for i in range(10)}:
        raise ValueError("e8")
    root = unpack()
    os.chdir(root)
    os.execv(sys.executable, [sys.executable, "-I", "-B", str(root / "c.py"), sys.argv[1]])

if __name__ == "__main__":
    try: result = main()
    except Exception:
        print("e9", file=sys.stderr)
        result = 1
    raise SystemExit(result)
