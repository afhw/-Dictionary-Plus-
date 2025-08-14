import re
import json


def parse_additional_material(text_content):
    parsed_data = {}
    current_level = "未知级别"
    current_char_type = "未知类型"

    # 移除不包含详细释义的索引部分
    content_to_parse = re.split(r'仅仅包括.*?形声字组', text_content)[0]
    blocks = re.split(r'(\n\s*《.*?》)', content_to_parse)

    context_text = blocks[0]

    for i in range(1, len(blocks), 2):
        header = blocks[i].strip()
        body = blocks[i + 1].strip()

        level_match = re.search(r"(一级|二级|三级)字表", context_text)
        if level_match: current_level = level_match.group(1)

        type_match = re.search(r"的(指事字|象形字|会意字)", context_text)
        if type_match: current_char_type = type_match.group(1)

        char_match = re.search(r"《(.)》", header)
        if char_match:
            char = char_match.group(1)
            explanation_text = f"{header[1:]} {body}"

            pinyin_match = re.search(r"读音\s*([a-zāáǎàēéěèīíǐìōóǒòūúǔùǖǘǚǜü]+)", explanation_text)
            pinyin = pinyin_match.group(1) if pinyin_match else ""

            definition_match = re.search(r"本义[为是]?\s*([^。，\n]+)", explanation_text)
            definition = definition_match.group(1).strip() if definition_match else ""

            parsed_data[char] = {
                "level": current_level,
                "authoritative_type": current_char_type,
                "new_explanation": explanation_text,
                "new_pinyin": pinyin,
                "new_definition": definition,
            }
        context_text = body
    return parsed_data


def create_new_entry(char, new_info):
    return {
        "glyph": char,
        "pinyin": new_info['new_pinyin'],
        "char_type": [new_info['authoritative_type']],
        "is_phonetic_radical": False,
        "definition": new_info['new_definition'],
        "analysis": {"explanation": new_info['new_explanation']},
        "phrases": [],
        "metadata": {"level": new_info['level'], "source": "additional_material"}
    }


# --- 主程序 ---
if __name__ == "__main__":
    try:
        with open("dictionary_database.json", "r", encoding="utf-8") as f:
            database_data = json.load(f)
        print(f"成功加载基础数据库 'dictionary_database.json'，包含 {len(database_data)} 个条目。")
    except (FileNotFoundError, json.JSONDecodeError):
        print("错误：未找到 'dictionary_database.json'。请先运行 'generate_json_database.py'。")
        exit()

    try:
        with open("additional_material.txt", "r", encoding="utf-16") as f:
            additional_text = f.read()
    except FileNotFoundError:
        print("错误：请将附加材料保存为 'additional_material.txt'。")
        exit()

    print("正在解析附加材料以进行更新和扩充...")
    new_char_info = parse_additional_material(additional_text)
    print(f"解析完成，提取了 {len(new_char_info)} 个字的权威信息。")

    update_count = 0
    add_count = 0
    for char, new_info in new_char_info.items():
        # setdefault 确保即使是新字也能被正确处理
        entry = database_data.setdefault(char, create_new_entry(char, new_info))

        if 'source' in entry.get('metadata', {}):  # 这是一个新创建的条目
            add_count += 1
        else:  # 这是一个需要更新的条目
            entry.setdefault('analysis', {})['explanation'] = new_info['new_explanation']
            char_types = entry.setdefault('char_type', [])
            if new_info['authoritative_type'] not in char_types:
                char_types.insert(0, new_info['authoritative_type'])

            if new_info['new_pinyin']: entry['pinyin'] = new_info['new_pinyin']
            if new_info['new_definition']: entry['definition'] = new_info['new_definition']

            entry.setdefault('metadata', {})['level'] = new_info['level']
            update_count += 1

    print(f"\n合并完成！")
    print(f"- {update_count} 个现有条目已被更新/扩充。")
    print(f"- {add_count} 个新条目已添加到数据库。")

    try:
        with open("dictionary_database.json", "w", encoding="utf-8") as f:
            json.dump(database_data, f, ensure_ascii=False, indent=4)
        print("\n成功将最终数据保存回 'dictionary_database.json'！")
    except Exception as e:
        print(f"\n写入文件时发生错误: {e}")