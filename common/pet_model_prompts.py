"""宠物内置高清模特图 Prompt 模板与默认品种库。

职责：
    提供摄影棚环境下宠物头部特写的统一 prompt 模板，以及首批 10 个品种的完整 prompt 行。
业务作用：
    Pet Stage1 生成 ``pet_model_prompts.csv``；Pet Stage2 读取 ``full_prompt`` 本地 Qwen-Image-2512 出图。
系统定位：
    宠物模特资产的内容层；后续可扩展品种或改为 Qwen 批量改写，CSV 列结构保持不变。
"""

from __future__ import annotations

import re
from dataclasses import dataclass

# 摄影棚头像：头部特写 + seamless 背景与专业布光（非居家场景、非全身）
PET_STUDIO_PORTRAIT_SCENE = (
    "专业商业宠物摄影棚实拍：宠物**头部大特写**，仅头部与肩颈入镜，可带耳朵，**不要**全身；"
    "背景为浅色无缝纸或浅灰 seamless 棚拍背景，柔和渐变虚化，有真实棚内空间感与明暗层次，"
    "**非**数码抠图纯白平面、**非**客厅/卧室/户外等生活场景；"
    "主光+辅光双层柔光箱，顶侧填充，面部光影均匀立体，无生硬死黑阴影；"
    "浅景深突出脸部，背景自然 bokeh。"
)

# 统一基础参数：所有品种 prompt 的前置约束
PET_MODEL_PROMPT_BASE = (
    "2K 超高清，8K 面部细节，极致锐化，"
    f"{PET_STUDIO_PORTRAIT_SCENE}"
    "面部毛发/胡须纹理清晰，眼神有光，"
    "单反 85mm 或 50mm f1.8 人像近摄，写实照片，原生相机直出，色彩自然，无水印无杂物。"
    "**气质**：超级可爱、温顺治愈、表情软萌亲和；毛色为该品种常见自然色，均匀干净；"
    "**不要**面部暗斑、雀斑、闪电纹、半脸分界、异瞳或任何显脏显怪的独家花纹；"
    "**不要**家居家具、绿植、街景等生活化背景元素。"
)

# 宠物昵称长度约束（英文按字母计，中文按汉字计）
PET_NAME_EN_MIN_LEN = 4
PET_NAME_EN_MAX_LEN = 6
PET_NAME_ZH_MIN_LEN = 2
PET_NAME_ZH_MAX_LEN = 4

_PET_NAME_EN_RE = re.compile(r"^[A-Za-z]+$")
_PET_NAME_ZH_RE = re.compile(r"^[\u4e00-\u9fff]+$")


@dataclass(frozen=True)
class PetModelPromptSpec:
    """单品种模特 prompt 规格。

    Attributes:
        species_id: 英文 snake_case 标识，用于文件名与 CSV。
        label_zh: 中文品种展示名。
        pet_name_en: 宠物英文昵称，4～6 个字母。
        pet_name_zh: 宠物中文昵称，2～4 个汉字。
        subject_desc: 品种面部与神态描述（特写主体段）。
    """

    species_id: str
    label_zh: str
    pet_name_en: str
    pet_name_zh: str
    subject_desc: str


def validate_pet_name_en(name: str) -> str:
    """校验英文宠物名：仅字母，长度 4～6。"""
    text = (name or "").strip()
    if not _PET_NAME_EN_RE.match(text):
        raise ValueError(f"pet_name_en 须为纯英文字母: {name!r}")
    n = len(text)
    if not (PET_NAME_EN_MIN_LEN <= n <= PET_NAME_EN_MAX_LEN):
        raise ValueError(
            f"pet_name_en 长度须 {PET_NAME_EN_MIN_LEN}～{PET_NAME_EN_MAX_LEN} 字母，"
            f"当前 {n}: {name!r}"
        )
    return text


def validate_pet_name_zh(name: str) -> str:
    """校验中文宠物名：仅汉字，长度 2～4。"""
    text = (name or "").strip()
    if not _PET_NAME_ZH_RE.match(text):
        raise ValueError(f"pet_name_zh 须为纯汉字: {name!r}")
    n = len(text)
    if not (PET_NAME_ZH_MIN_LEN <= n <= PET_NAME_ZH_MAX_LEN):
        raise ValueError(
            f"pet_name_zh 长度须 {PET_NAME_ZH_MIN_LEN}～{PET_NAME_ZH_MAX_LEN} 汉字，"
            f"当前 {n}: {name!r}"
        )
    return text


# 首批内置 10 个品种；摄影棚头部特写，强调可爱自然
DEFAULT_PET_MODEL_SPECS: tuple[PetModelPromptSpec, ...] = (
    PetModelPromptSpec(
        species_id="golden_retriever",
        label_zh="金毛巡回犬",
        pet_name_en="Sunny",
        pet_name_zh="阳光",
        subject_desc=(
            "成年浅金色金毛，头部大特写，毛色均匀柔和，蓬松耳周金毛，"
            "圆润黑鼻头，眼神温柔明亮，嘴角微扬像在微笑，正对镜头"
        ),
    ),
    PetModelPromptSpec(
        species_id="pomeranian",
        label_zh="博美犬",
        pet_name_en="Mochi",
        pet_name_zh="团团",
        subject_desc=(
            "成年奶油橙貂色博美，头部大特写，球状蓬松脸毛，大而亮的黑眼，"
            "神态俏皮可爱，毛发柔软干净"
        ),
    ),
    PetModelPromptSpec(
        species_id="corgi",
        label_zh="柯基犬",
        pet_name_en="Coco",
        pet_name_zh="豆豆",
        subject_desc=(
            "成年经典三色柯基，头部大特写，圆脸大耳，笑眼友善看向镜头，"
            "面部干净无杂斑，萌态十足"
        ),
    ),
    PetModelPromptSpec(
        species_id="samoyed",
        label_zh="萨摩耶",
        pet_name_en="Snowy",
        pet_name_zh="雪球",
        subject_desc=(
            "成年纯白萨摩耶，头部大特写，雪白耳周绒毛，经典「微笑」表情，"
            "黑鼻头与明亮双眼，天使般治愈"
        ),
    ),
    PetModelPromptSpec(
        species_id="shiba_inu",
        label_zh="柴犬",
        pet_name_en="Kuma",
        pet_name_zh="柴柴",
        subject_desc=(
            "成年赤色柴犬，头部大特写，被毛短密色泽均匀，面部线条干净，"
            "眼神警觉而温顺，略带矜持的可爱"
        ),
    ),
    PetModelPromptSpec(
        species_id="poodle",
        label_zh="标准贵宾犬",
        pet_name_en="Bella",
        pet_name_zh="卷卷",
        subject_desc=(
            "成年浅杏色标准贵宾，头部大特写，卷毛蓬松有型，面部干净柔和，"
            "聪慧可爱，耳周卷毛清晰"
        ),
    ),
    PetModelPromptSpec(
        species_id="husky",
        label_zh="哈士奇",
        pet_name_en="Frost",
        pet_name_zh="冰蓝",
        subject_desc=(
            "成年灰白哈士奇，头部大特写，经典柔和灰白毛，双瞳同色清澈，"
            "神态活泼友好、略带傻萌"
        ),
    ),
    PetModelPromptSpec(
        species_id="french_bulldog",
        label_zh="法国斗牛犬",
        pet_name_en="Bruno",
        pet_name_zh="胖墩",
        subject_desc=(
            "成年浅虎斑法国斗牛犬，头部大特写，短鼻圆脸，表情憨萌，"
            "面部干净，短毛质感清晰"
        ),
    ),
    PetModelPromptSpec(
        species_id="british_shorthair",
        label_zh="英国短毛猫",
        pet_name_en="Minty",
        pet_name_zh="蓝宝",
        subject_desc=(
            "成年蓝灰英国短毛猫，头部大特写，银渐层毛色柔和，圆脸铜色大眼，"
            "面部干净，气质软萌稳重"
        ),
    ),
    PetModelPromptSpec(
        species_id="ragdoll",
        label_zh="布偶猫",
        pet_name_en="Luna",
        pet_name_zh="绵绵",
        subject_desc=(
            "成年海豹双色布偶猫，头部大特写，重点色面部自然柔和，湛蓝双眼，"
            "中长丝质颈周毛，温顺仙气可爱"
        ),
    ),
)

PET_MODEL_PROMPTS_CSV_FIELDS: tuple[str, ...] = (
    "species_id",
    "label_zh",
    "pet_name_en",
    "pet_name_zh",
    "prompt_base",
    "subject_desc",
    "full_prompt",
    "output_filename",
)


def build_full_pet_model_prompt(subject_desc: str, *, prompt_base: str | None = None) -> str:
    """将品种主体与统一摄影棚参数合成为 Qwen-Image 用完整 prompt。"""
    base = (prompt_base or PET_MODEL_PROMPT_BASE).strip()
    subject = subject_desc.strip()
    tail = (
        "商业宠物摄影棚头像照，头部与肩颈特写，浅色 seamless 棚拍背景柔和虚化，"
        "双层柔光箱专业布光，面部清晰可爱，真实棚拍质感，2K 分辨率，"
        "禁止生活家居/户外场景与全身构图。"
    )
    return f"{base} {subject}，{tail}"


def default_pet_model_prompt_rows(
    *,
    prompt_base: str | None = None,
    specs: tuple[PetModelPromptSpec, ...] | None = None,
) -> list[dict[str, str]]:
    """生成默认 10 行 prompt 字典列表，供 CSV 写入。"""
    base = (prompt_base or PET_MODEL_PROMPT_BASE).strip()
    chosen = specs or DEFAULT_PET_MODEL_SPECS
    rows: list[dict[str, str]] = []
    for spec in chosen:
        name_en = validate_pet_name_en(spec.pet_name_en)
        name_zh = validate_pet_name_zh(spec.pet_name_zh)
        full = build_full_pet_model_prompt(spec.subject_desc, prompt_base=base)
        rows.append(
            {
                "species_id": spec.species_id,
                "label_zh": spec.label_zh,
                "pet_name_en": name_en,
                "pet_name_zh": name_zh,
                "prompt_base": base,
                "subject_desc": spec.subject_desc,
                "full_prompt": full,
                "output_filename": f"{spec.species_id}.png",
            }
        )
    return rows
