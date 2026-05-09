"""将各服装模板 ``high_poly/body.obj`` 中的 Wavefront ``o`` / ``g`` 指令整理为 Blender 友好形态。

Wavefront OBJ 里每个 ``o <name>`` 会在 Blender 中变成独立物体；本脚本：

- 若存在多个 ``o``：保留第一条为 ``o body``，**删除**其余 ``o`` 行（后续面归入同一物体，与常见合并 OBJ 写法一致）；
- 若仅有一个 ``o``：仅把名称改为 ``o body``；
- 若没有任何 ``o``：仅删除所有 ``g`` 行（若有）；若也无 ``g``，则跳过并打印说明（需人工处理 ``o``）；
- **顺带删除**所有 ``g ...`` 组行（ZBrush 等导出里常见 ``g ZBrushPolyMesh3D``，与根物体名无关，删掉可避免多余分组）。

在仓库根目录、**已** ``conda activate figshion3d``（见 ``.cursorrules``；该环境含 ``python-dotenv`` 与 ``requirements.txt`` 依赖）下执行::

    python stage1_body_template_preview/fix_obj_object_name_to_body.py
    python stage1_body_template_preview/fix_obj_object_name_to_body.py --dry-run

模板根目录与 ``.env`` 由 ``common.settings.SETTINGS`` 提供（与流水线其它 stage 一致）。
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from common.settings import SETTINGS


def is_o_line(line: str) -> bool:
    s = line.lstrip("\ufeff").rstrip("\r\n")
    if len(s) < 1 or s[0] != "o":
        return False
    if len(s) == 1:
        return True
    return s[1] in " \t"


def is_g_line(line: str) -> bool:
    """Wavefront ``g`` 分组行（非 ``gn`` / ``grid`` 等误匹配：要求行首为 ``g`` 且后跟空白或行末）。"""
    s = line.lstrip("\ufeff").rstrip("\r\n")
    if len(s) < 1 or s[0] != "g":
        return False
    if len(s) == 1:
        return True
    return s[1] in " \t"


def first_o_name(line: str) -> str:
    s = line.strip()
    if not s.startswith("o"):
        return ""
    rest = s[1:].lstrip()
    return rest


def line_ending(line: str) -> str:
    if line.endswith("\r\n"):
        return "\r\n"
    if line.endswith("\r"):
        return "\r"
    return "\n"


def strip_g_lines(lines: list[str]) -> tuple[list[str], list[str]]:
    """去掉所有 ``g`` 行；返回 (新行列表, 被删行的去换行样本，最多 5 条)。"""
    removed_sample: list[str] = []
    kept: list[str] = []
    for ln in lines:
        if is_g_line(ln):
            if len(removed_sample) < 5:
                removed_sample.append(ln.rstrip("\r\n"))
        else:
            kept.append(ln)
    return kept, removed_sample


def process_obj(obj_path: Path, template_root: Path, *, dry_run: bool, backup: bool) -> list[str]:
    """返回人类可读改动说明（可多行）；无需修改时返回空列表。"""
    raw = obj_path.read_bytes()
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError:
        text = raw.decode("latin-1", errors="replace")

    lines = text.splitlines(keepends=True)
    if not lines:
        return [f"[SKIP] {obj_path}: 空文件"]

    o_indices = [i for i, ln in enumerate(lines) if is_o_line(ln)]
    g_count = sum(1 for ln in lines if is_g_line(ln))
    traces: list[str] = []

    if not o_indices and g_count == 0:
        return [f"[SKIP] {obj_path}: 无 ``o`` 且无 ``g``，请人工检查"]

    need_o_fix = False
    old_first = ""
    old_name = "(空)"
    first_i = o_indices[0] if o_indices else -1

    if o_indices:
        old_first = lines[first_i].rstrip("\r\n")
        old_name = first_o_name(lines[first_i]) or "(空)"
        ending = line_ending(lines[first_i])
        new_first = "o body" + ending
        need_o_fix = lines[first_i] != new_first or len(o_indices) > 1

        removed_o: list[str] = []
        if len(o_indices) > 1:
            for idx in o_indices[1:]:
                removed_o.append(lines[idx].rstrip("\r\n"))
            traces.append(
                f"  合并 {len(o_indices)} 个 ``o`` 物体为单一物体：删除后续 {len(o_indices) - 1} 条 ``o`` 行"
            )
            for ln in removed_o[:5]:
                traces.append(f"    - 删除 o: {ln}")
            if len(removed_o) > 5:
                traces.append(f"    - … 共省略 {len(removed_o) - 5} 条 o 行")

    need_g_strip = g_count > 0
    need_rewrite = need_o_fix or need_g_strip

    if not need_rewrite:
        return []

    rel = obj_path.relative_to(template_root) if obj_path.is_relative_to(template_root) else obj_path
    header = f"[FIX] {rel}"
    out_lines: list[str] = [header]
    if need_o_fix:
        out_lines.append(f"  首物体名称: {old_name!r} -> 'body'（原行: {old_first!r}）")
        out_lines.extend(traces)
    elif o_indices:
        out_lines.append(f"  ``o`` 已为 body 且单物体；仅处理 ``g``")
    else:
        out_lines.append("  无 ``o`` 指令；仅删除 ``g`` 行")

    if need_g_strip:
        _, g_samples = strip_g_lines(lines)
        out_lines.append(f"  删除 {g_count} 条 ``g`` 组行")
        for ln in g_samples:
            out_lines.append(f"    - 删除 g: {ln}")
        if g_count > len(g_samples):
            out_lines.append(f"    - … 共省略 {g_count - len(g_samples)} 条 g 行")

    if dry_run:
        out_lines.insert(1, "  (dry-run 未写回磁盘)")
        return out_lines

    new_lines = lines[:]
    if need_o_fix:
        new_lines[first_i] = "o body" + line_ending(lines[first_i])
        for idx in reversed(o_indices[1:]):
            del new_lines[idx]

    new_lines, _ = strip_g_lines(new_lines)

    if backup:
        bak = obj_path.with_suffix(obj_path.suffix + ".bak")
        shutil.copy2(obj_path, bak)
        out_lines.append(f"  已备份: {bak.name}")

    obj_path.write_bytes("".join(new_lines).encode("utf-8"))
    out_lines.append("  已写回 body.obj")
    return out_lines


def main() -> int:
    parser = argparse.ArgumentParser(description="将模板 body.obj 的 o 规范为 o body，并删除所有 g 行")
    parser.add_argument(
        "--template-root",
        type=Path,
        default=None,
        help="覆盖 SETTINGS.template_root（默认来自 BODY_TEMPLATE_ROOT / .env）",
    )
    parser.add_argument("--dry-run", action="store_true", help="只打印将发生的改动，不写文件")
    parser.add_argument("--no-backup", action="store_true", help="写回前不生成 .obj.bak")
    args = parser.parse_args()

    root = (args.template_root or SETTINGS.template_root).resolve()
    if not root.is_dir():
        print(f"模板根目录不存在: {root}", file=sys.stderr)
        return 1

    fixed = 0
    skipped = 0
    for template_dir in sorted(p for p in root.iterdir() if p.is_dir()):
        obj_path = template_dir / "high_poly" / "body.obj"
        if not obj_path.is_file():
            print(f"[SKIP] {template_dir.name}: 无 high_poly/body.obj")
            skipped += 1
            continue
        traces = process_obj(
            obj_path,
            root,
            dry_run=args.dry_run,
            backup=not args.no_backup,
        )
        if not traces:
            print(f"[OK]   {template_dir.name}: 已是单一 o body 且无 g 行，无需修改")
            continue
        fixed += 1
        print("\n".join(traces))

    print(f"\n完成: 修改 {fixed} 个，缺文件跳过 {skipped} 个模板目录。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
