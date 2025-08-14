import re
import json


def parse_char_details(text_block):
    """从单个字的文本描述中提取所有结构化信息。"""
    details = {}
    pinyin_match = re.search(r"读音\s*([a-zāáǎàēéěèīíǐìōóǒòūúǔùǖǘǚǜü]+)", text_block)
    details['pinyin'] = pinyin_match.group(1) if pinyin_match else ""
    types = set()
    if "形声" in text_block: types.add("形声字")
    if "会意" in text_block: types.add("会意字")
    if "象形" in text_block: types.add("象形字")
    if "指事" in text_block: types.add("指事字")
    details['char_type'] = list(types) if types else []
    definition_match = re.search(r"本义[为是]?\s*([^。，\n]+)", text_block)
    details['definition'] = definition_match.group(1).strip() if definition_match else ""
    details['explanation'] = text_block.strip()
    return details


def build_final_database(source_text, additional_text):
    """
    一个统一的解析器，用于从两个源文件构建最终数据库。
    """
    db = {}

    # --- 阶段 1: 建立所有形声字组关系 ---
    # 格式: 0558、奴——怒努弩...
    main_group_pattern = re.compile(r"(\d{4,5})、?\s*([^——\n]+)——\s*([^\d\n]+)")
    for _, radical_str, derived_str in main_group_pattern.findall(source_text):
        radical = radical_str.strip()
        db.setdefault(radical, {"glyph": radical})['is_phonetic_radical'] = True
        for char in list(derived_str.strip()):
            db.setdefault(char, {"glyph": char})
            db[char]['components'] = {"phonetic_radical": radical}

    # 格式: 刁：叼汈。
    two_char_pattern = re.compile(r"([一-龥])：([一-龥]+)。")
    for radical, derived_str in two_char_pattern.findall(source_text):
        db.setdefault(radical, {"glyph": radical})['is_phonetic_radical'] = True
        for char in list(derived_str):
            db.setdefault(char, {"glyph": char})
            db[char]['components'] = {"phonetic_radical": radical}

    # 格式: 《次》，其形声边为二
    one_char_pattern = re.compile(r"《(.)》，其形声边为([^，、\s\(\)]+)")
    for derived_char, radical in one_char_pattern.findall(source_text):
        db.setdefault(radical, {"glyph": radical})['is_phonetic_radical'] = True
        db.setdefault(derived_char, {"glyph": derived_char})
        db[derived_char]['components'] = {"phonetic_radical": radical}

    print(f"阶段1：形声字组关系建立完成。")

    # --- 阶段 2: 从两个文件中解析并填充所有汉字的详细信息 ---
    all_text = source_text + "\n" + additional_text
    char_blocks = re.split(r"\n\s*(?=《)", all_text)

    for block in char_blocks:
        block = block.strip()
        if not block.startswith("《"): continue
        char_match = re.match(r"《(.)》", block)
        if not char_match: continue

        char = char_match.group(1)
        content = block[len(char) + 2:].strip()

        entry = db.setdefault(char, {"glyph": char})
        details = parse_char_details(content)

        entry['pinyin'] = details['pinyin'] or entry.get('pinyin')
        entry['definition'] = details['definition'] or entry.get('definition')

        existing_types = set(entry.get('char_type', []))
        new_types = set(details['char_type'])
        entry['char_type'] = list(existing_types.union(new_types))

        if char in additional_text:
            entry['analysis'] = {"explanation": details['explanation']}
        else:
            entry.setdefault('analysis', {})['explanation'] = details['explanation']

        entry.setdefault('phrases', [])

    print(f"阶段2：汉字详细信息填充完成。")
    return db


# --- 主程序 ---
if __name__ == "__main__":
    try:
        with open("source_material.txt", "r", encoding="utf-16") as f:
            source_text = f.read()
        with open("additional_material.txt", "r", encoding="utf-16") as f:
            additional_text = f.read()
    except FileNotFoundError as e:
        print(f"错误：请确保 '{e.filename}' 文件存在于脚本相同目录下。")
        exit()

    print("开始构建数据库...")
    database = build_final_database(source_text, additional_text)
    print(f"初步构建完成，总条目数: {len(database)}")

    # --- 【新增】阶段 3: 清理数据库，移除无释义的空条目 ---
    print("阶段3: 开始清理数据库...")
    chars_to_delete = []
    for char, entry in database.items():
        # 定义一个“空”条目的标准：没有拼音，没有定义，也没有任何解释文本
        is_empty = (
                not entry.get('pinyin') and
                not entry.get('definition') and
                not entry.get('analysis', {}).get('explanation')
        )
        if is_empty:
            chars_to_delete.append(char)

    if chars_to_delete:
        print(f"找到 {len(chars_to_delete)} 个空条目需要移除 (例如: {chars_to_delete[:5]}...)")
        for char in chars_to_delete:
            del database[char]
        print("清理完成。")
    else:
        print("数据库无需清理。")

    # --- 最终整理和保存 ---
    for char, entry in database.items():
        entry.setdefault('is_phonetic_radical', False)

    print(f"最终数据库构建完成，总条目数: {len(database)}")

    try:
        with open("dictionary_database.json", "w", encoding="utf-8") as f:
            json.dump(database, f, ensure_ascii=False, indent=4)
        print("\n成功！最终数据库已保存到 'dictionary_database.json'。")
    except Exception as e:
        print(f"写入文件时发生错误: {e}")