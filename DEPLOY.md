# ZM-QQGroupmgr 部署指南

## 📋 前置要求

- AstrBot >= 3.4.0
- Python >= 3.8
- 支持的平台适配器：aiocqhttp 或 nakuru

## 🚀 快速部署

### 1. 通过 AstrBot 插件市场安装（推荐）

1. 访问 [AstrBot 插件市场](https://cloud.astrbot.app/market)
2. 搜索 "ZM-QQGroupmgr"
3. 点击安装
4. 重启 AstrBot

### 2. 手动安装

```bash
# 进入 AstrBot 插件目录
cd /path/to/astrbot/plugins

# 克隆仓库
git clone https://github.com/ZomebieMask/astrbot_plugin_zm_qqgroupmgr.git

# 重启 AstrBot
```

### 3. 下载压缩包安装

1. 从 [Releases](https://github.com/ZomebieMask/astrbot_plugin_zm_qqgroupmgr/releases) 下载最新版本
2. 解压到 AstrBot 的 `plugins` 目录
3. 确保目录结构为：`plugins/ZM-QQGroupmgr/main.py`
4. 重启 AstrBot

## ⚙️ 配置机器人权限

### QQ 群权限设置

1. **将机器人设为管理员或群主**
   - 进入群设置 → 群管理 → 设置管理员
   - 选择机器人账号并设为管理员

2. **验证权限**
   - 发送 `/mute @测试用户 1m` 测试禁言功能
   - 如果提示权限不足，请检查机器人是否为管理员

### 功能权限对照表

| 功能 | 需要权限 | 说明 |
|------|---------|------|
| 禁言 | 管理员 | 必须 |
| 踢人 | 管理员 | 必须 |
| 撤回消息 | 管理员 | 必须 |
| 设置管理员 | 群主 | 仅群主可用 |
| 设置头衔 | 群主 | 仅群主可用 |

## 📊 初次使用建议

### 1. 配置欢迎消息

```
/wel set 欢迎 {at} 加入本群！请遵守群规。
```

### 2. 开启广告拦截

```
/adban on
```

### 3. 设置群广告

```
/ad set 本群禁止发布广告，违者将被封禁！
```

### 4. 测试功能

```
# 测试禁言（对自己）
/mute @自己 1m

# 测试撤回
/recall 1

# 查看欢迎状态
/wel status
```

## 🔧 常见问题

### Q1: 命令无响应

**解决方案**:
1. 检查 AstrBot 日志：`插件是否加载成功`
2. 确认命令格式正确，以 `/` 开头
3. 检查机器人是否在线

### Q2: 提示权限不足

**解决方案**:
1. 确认机器人是否为群管理员
2. 某些功能（如设置头衔）需要群主权限
3. 检查 QQ 账号是否被风控

### Q3: 广告拦截误判

**解决方案**:
1. 广告检测基于评分机制，阈值为 6 分
2. 如果误判率高，可以暂时关闭：`/adban off`
3. 未来版本将支持自定义规则

### Q4: 消息撤回失败

**解决方案**:
1. QQ 消息撤回有 2 分钟时限
2. 确认机器人有撤回权限
3. 检查消息是否在记录中

### Q5: 封禁用户仍能进群

**解决方案**:
1. 封禁列表基于插件 KV 存储
2. 确认插件正在运行
3. 检查日志中的封禁记录

## 📈 性能优化

### 消息历史记录

默认每个群保存 100 条消息历史。如需调整：

1. 修改 `main.py` 中的 `self.max_history_per_group`
2. 重启插件

### 广告检测优化

如果群消息量大，可以考虑：
1. 仅在必要时开启广告拦截
2. 调整检测阈值（需修改代码）

## 🔒 安全建议

1. **定期检查封禁列表**
   - 封禁列表存储在 KV 数据库中
   - 建议定期清理过期封禁

2. **谨慎使用批量操作**
   - `/kick <时间>` 会批量踢人
   - 建议先小范围测试

3. **备份配置**
   - 定期备份 AstrBot 的数据目录
   - 包含所有群配置和封禁列表

## 📝 数据存储位置

插件数据存储在 AstrBot 的 KV 数据库中：

```
数据库键名格式:
- zm_qqmanager_banlist_{群号}     # 封禁列表
- zm_qqmanager_ad_{群号}          # 广告内容
- zm_qqmanager_welcome_{群号}     # 欢迎消息
- zm_qqmanager_adban_{群号}       # 广告拦截开关
```

## 🔄 更新插件

### 通过 Git 更新

```bash
cd /path/to/astrbot/plugins/ZM-QQGroupmgr
git pull
```

### 手动更新

1. 下载最新版本
2. 备份当前版本（可选）
3. 覆盖旧文件
4. 重启 AstrBot

**注意**: 更新不会覆盖 KV 数据库中的配置。

## 📞 技术支持

- GitHub Issues: [提交问题](https://github.com/ZomebieMask/astrbot_plugin_zm_qqgroupmgr/issues)
- AstrBot 社区: [访问论坛](https://astrbot.app)
- 文档中心: [查看文档](https://docs.astrbot.app)

## 🎯 最佳实践

1. **分级管理**: 为不同管理员设置不同权限
2. **规则透明**: 在群公告中说明管理规则
3. **适度管理**: 避免过度使用自动化功能
4. **定期维护**: 定期清理不活跃成员和封禁列表
5. **测试环境**: 在测试群中先测试新功能

---

如有其他问题，欢迎提交 Issue 或查阅完整文档。
