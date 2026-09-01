# 🚀 ZM-QQGroupmgr 快速开始

> 5分钟快速上手 ZM-QQGroupmgr 插件

## 📦 安装

### 方法 1: AstrBot 插件市场（推荐）
```
1. 打开 AstrBot WebUI
2. 进入「插件市场」
3. 搜索 "ZM-QQGroupmgr"
4. 点击「安装」
5. 重启 AstrBot
```

### 方法 2: 手动安装
```bash
cd /path/to/astrbot/plugins
git clone https://github.com/ZomebieMask/astrbot_plugin_zm_qqgroupmgr.git
# 重启 AstrBot
```

## ⚙️ 配置权限

**将机器人设为群管理员**（必需）
1. 进入 QQ 群设置
2. 群管理 → 设置管理员
3. 选择机器人账号

## 🎯 常用命令

### 禁言用户
```
/mute @用户 30d        # 禁言30天
/mute 123456 1w        # 禁言1周
```

### 踢出成员
```
/kick @用户            # 踢出指定用户
/kick 30d              # 踢出30天未发言的成员
```

### 封禁管理
```
/ban @用户             # 封禁并踢出
/unban 123456          # 解除封禁
```

### 欢迎消息
```
/wel set 欢迎 {at} 加入本群！  # 设置欢迎消息
/wel on                        # 开启自动欢迎
/wel status                    # 查看状态
```

### 广告拦截
```
/adban on              # 开启广告拦截
/ad set 本群禁止广告   # 设置群广告
```

### 消息撤回
```
/recall                # 撤回被回复的消息
/recall 5              # 撤回最近5条消息
```

## 🎮 占位符

在欢迎消息和广告中使用：

- `{at}` - @该用户
- `{name}` - 用户昵称
- `{user_id}` - QQ号
- `{group_id}` - 群号

**示例**:
```
/wel set 欢迎 {name} (QQ: {user_id}) 加入群 {group_id}！
```

## 📖 完整文档

- [完整功能文档](README.md)
- [部署指南](DEPLOY.md)
- [GitHub 发布](GITHUB_GUIDE.md)

## ❓ 遇到问题？

1. 检查机器人是否有管理员权限
2. 查看 [常见问题](DEPLOY.md#常见问题)
3. 提交 [GitHub Issue](https://github.com/ZomebieMask/astrbot_plugin_zm_qqgroupmgr/issues)

---

**开始使用**: 在群里发送 `/mute` 试试吧！ 🎉
