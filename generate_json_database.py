import re
import json


def parse_char_details(text_block):
    """从单个字的文本描述中提取所有结构化信息。"""
    details = {}
    pinyin_match = re.search(r"读音[为是]?\s*([a-zāáǎàēéěèīíǐìōóǒòūúǔùǖǘǚǜü]+)", text_block)
    details['pinyin'] = pinyin_match.group(1) if pinyin_match else ""
    types = set()
    if "形声" in text_block: types.add("形声字")
    if "会意" in text_block: types.add("会意字")
    if "象形" in text_block: types.add("象形字")
    if "指事" in text_block: types.add("指事字")
    details['char_type'] = list(types) if types else ["未知类型"]
    definition_match = re.search(r"本义[为是]?\s*([^。，\n]+)", text_block)
    details['definition'] = definition_match.group(1).strip() if definition_match else ""
    details['explanation'] = text_block.strip()
    return details


def build_database_from_source(source_text):
    """
    一个全新的、多阶段的解析器，用于从 source_material.txt 构建数据库。
    """
    db = {}

    # --- 阶段 1: 解析所有详细释义块 ---
    char_blocks = re.split(r"\n\s*(?=《)", source_text)
    for block in char_blocks:
        block = block.strip()
        if not block.startswith("《"): continue
        char_match = re.match(r"《(.)》", block)
        if not char_match: continue
        char = char_match.group(1)
        content = block[len(char) + 2:].strip()

        details = parse_char_details(content)
        db[char] = {
            "glyph": char,
            "pinyin": details['pinyin'],
            "char_type": details['char_type'],
            "definition": details['definition'],
            "analysis": {"explanation": details['explanation']},
            "phrases": []
        }

    # --- 阶段 2: 解析所有形声字组关系 ---
    # 格式: 0558、奴——怒努弩...
    main_group_pattern = re.compile(r"(\d{4,5})、?\s*([^——\n]+)——\s*([^\d\n]+)")
    matches = main_group_pattern.findall(source_text)
    for _, radical_str, derived_str in matches:
        radical = radical_str.strip()
        db.setdefault(radical, {"glyph": radical})['is_phonetic_radical'] = True
        for char in list(derived_str.strip()):
            db.setdefault(char, {"glyph": char})
            db[char]['components'] = {"phonetic_radical": radical}

    # 格式: 刁：叼汈。
    two_char_pattern = re.compile(r"([一-龥])：([一-龥]+)。")
    matches = two_char_pattern.findall(source_text)
    for radical, derived_str in matches:
        db.setdefault(radical, {"glyph": radical})['is_phonetic_radical'] = True
        for char in list(derived_str):
            db.setdefault(char, {"glyph": char})
            db[char]['components'] = {"phonetic_radical": radical}

    # 格式: 《次》，其形声边为二
    one_char_pattern = re.compile(r"《(.)》，其形声边为([^，、\s\(\)]+)")
    matches = one_char_pattern.findall(source_text)
    for derived_char, radical in matches:
        db.setdefault(radical, {"glyph": radical})['is_phonetic_radical'] = True
        db.setdefault(derived_char, {"glyph": derived_char})
        db[derived_char]['components'] = {"phonetic_radical": radical}

    return db


# --- 主程序 ---
if __name__ == "__main__":
    try:
        with open("source_material.txt", "r", encoding="utf-16") as f:
            source_text = f.read()
    except FileNotFoundError:
        print("错误：请确保 'source_material.txt' 文件存在。")
        exit()

    print("开始从源材料构建基础数据库...")
    database = build_database_from_source(source_text)
    print(f"基础数据库构建完成，包含 {len(database)} 个条目。")

    try:
        with open("dictionary_database.json", "w", encoding="utf-8") as f:
            json.dump(database, f, ensure_ascii=False, indent=4)
        print("成功！基础数据库已保存到 'dictionary_database.json'。")
        print("下一步，请运行 'update_database.py' 来补充权威数据。")
    except Exception as e:
        print(f"写入文件时发生错误: {e}")