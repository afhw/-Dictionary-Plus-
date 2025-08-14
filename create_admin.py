import hashlib
import secrets
import getpass


def create_admin_password_hash():
    """
    安全地创建管理员密码哈希，并以 'salt$hash' 格式输出。
    """
    # 1. 使用 getpass 安全地获取用户输入的密码，不会在屏幕上显示
    password = input("请输入新的管理员密码: ")
    password_confirm = input("请再次确认密码: ")

    if password != password_confirm:
        print("\n错误：两次输入的密码不匹配。")
        return

    if not password:
        print("\n错误：密码不能为空。")
        return

    # 2. 生成一个安全的随机盐 (salt)
    salt = secrets.token_bytes(16)

    # 3. 使用 PBKDF2-HMAC-SHA256 算法生成密钥（哈希）
    # 迭代次数设为 260,000，这是一个行业推荐的安全值
    derived_key = hashlib.pbkdf2_hmac(
        'sha256',
        password.encode('utf-8'),
        salt,
        260000
    )

    # 4. 将盐和哈希转换为十六进制字符串，并用 '$' 分隔
    salt_hex = salt.hex()
    key_hex = derived_key.hex()

    stored_hash = f"{salt_hex}${key_hex}"

    print("\n✅ 密码哈希生成成功！")
    print("请将下面这行完整的哈希值复制到您的 config.json 文件中的 'ADMIN_PASSWORD_HASH' 字段：")
    print("-" * 70)
    print(stored_hash)
    print("-" * 70)


if __name__ == '__main__':
    create_admin_password_hash()