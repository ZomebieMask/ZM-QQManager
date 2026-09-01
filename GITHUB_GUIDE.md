# 如何将 ZM-QQManager 发布到 GitHub 和 AstrBot 插件市场

## 📝 概述

本文档指导你完成以下步骤：
1. 将插件上传到 GitHub
2. 在 AstrBot 插件市场发布插件

## 🚀 第一步：上传到 GitHub

### 选项 A: 使用 GitHub Web 界面（推荐新手）

1. **创建 GitHub 仓库**
   - 访问 https://github.com/new
   - 仓库名称：`ZM-QQManager`
   - 描述：`功能强大的 QQ 群管理插件 for AstrBot`
   - 选择 `Public`（公开）
   - **不要**勾选 "Add a README file"（我们已经有了）
   - 点击 `Create repository`

2. **获取仓库 URL**
   - 创建后会看到快速设置页面
   - 复制仓库 URL，例如：`https://github.com/ZomebieMask/astrbot_plugin_zm_qqmanager.git`

3. **推送代码**
   ```bash
   # 在插件目录下执行
   cd E:\claude-workspace\astrbot-plugins\ZM-QQManager
   
   # 添加远程仓库（替换 yourusername 为你的 GitHub 用户名）
   git remote add origin https://github.com/ZomebieMask/astrbot_plugin_zm_qqmanager.git
   
   # 推送代码
   git branch -M main
   git push -u origin main
   ```

4. **输入 GitHub 凭据**
   - 用户名：你的 GitHub 用户名
   - 密码：需要使用 Personal Access Token (PAT)
     - 获取 PAT：https://github.com/settings/tokens
     - 点击 `Generate new token (classic)`
     - 勾选 `repo` 权限
     - 复制生成的 token 作为密码

### 选项 B: 使用 GitHub CLI（推荐高级用户）

```bash
# 安装 GitHub CLI
# Windows: winget install GitHub.cli
# Mac: brew install gh
# Linux: 参考 https://cli.github.com/manual/installation

# 登录 GitHub
gh auth login

# 创建仓库并推送
cd E:\claude-workspace\astrbot-plugins\ZM-QQManager
gh repo create astrbot_plugin_zm_qqmanager --public --source=. --remote=origin --push
```

### 第二步：完善 GitHub 仓库

1. **添加 Topics（标签）**
   - 进入仓库页面
   - 点击右侧 `About` 旁的齿轮图标
   - 添加 topics：`astrbot`, `qq-bot`, `group-management`, `plugin`, `python`

2. **创建 Release**
   - 点击右侧 `Releases` → `Create a new release`
   - Tag version: `v1.0.0`
   - Release title: `ZM-QQManager v1.0.0`
   - 描述：复制 CHANGELOG.md 的内容
   - 点击 `Publish release`

3. **更新 metadata.yaml**
   - 将 `repo` 字段改为你的实际仓库地址
   - 例如：`https://github.com/ZomebieMask/astrbot_plugin_zm_qqmanager`
   - 提交更新：
   ```bash
   git add metadata.yaml
   git commit -m "chore: 更新仓库地址"
   git push
   ```

## 🌟 第三步：发布到 AstrBot 插件市场

### 前置要求

- ✅ 已将插件上传到 GitHub
- ✅ 仓库是 Public（公开）
- ✅ metadata.yaml 中的 repo 字段已更新
- ✅ 插件大小 < 16MB

### 发布步骤

1. **注册/登录账号**
   - 访问 https://cloud.astrbot.app/publish
   - 如果没有账号，先注册

2. **提交插件**
   - 点击「发布新插件」或类似按钮
   - 输入 GitHub 仓库 URL：`https://github.com/ZomebieMask/astrbot_plugin_zm_qqmanager`
   - 点击「提交」

3. **自动解析**
   - 系统会自动读取你的 `metadata.yaml`
   - 检查解析结果是否正确

4. **确认发布**
   - 检查插件信息：
     - 名称：ZM-QQManager
     - 版本：1.0.0
     - 作者：ZM
     - 描述：功能是否完整
   - 确认无误后点击「发布」

5. **等待审核**
   - 通常会自动通过（如果符合规范）
   - 如果有问题，会收到邮件通知

### 发布后

1. **查看插件页面**
   - 在插件市场搜索 `ZM-QQManager`
   - 确认信息显示正确

2. **测试安装**
   - 在测试环境尝试安装
   - 验证所有功能正常

3. **社区推广**（可选）
   - AstrBot 社区发帖介绍
   - 相关 QQ 群分享

## 🔄 更新插件

### 1. 修改代码并提交

```bash
# 修改文件后
git add .
git commit -m "feat: 添加新功能"
git push
```

### 2. 更新版本号

编辑 `metadata.yaml`：
```yaml
version: 1.0.1  # 从 1.0.0 改为 1.0.1
```

提交：
```bash
git add metadata.yaml
git commit -m "chore: 发布 v1.0.1"
git tag v1.0.1
git push && git push --tags
```

### 3. 在插件市场更新

- 插件市场会自动检测仓库更新
- 或手动在插件管理页面触发更新

## 📋 发布注意事项

### metadata.yaml 规范

- `name`: 必须是英文，不能重复
- `version`: 遵循语义化版本（Semantic Versioning）
- `repo`: 必须是完整的 GitHub 仓库 URL
- `desc`: 支持 Markdown 格式

### 大小限制

- 插件压缩包不能超过 16MB
- 使用 `.gitignore` 排除不必要的文件
- 避免包含大型依赖库

### 最佳实践

1. **版本管理**
   - 每次更新创建 Git Tag
   - 在 GitHub 创建 Release

2. **文档维护**
   - 保持 README.md 更新
   - 记录 CHANGELOG.md

3. **代码质量**
   - 添加错误处理
   - 编写清晰的注释
   - 测试所有功能

## 🆘 常见问题

### Q: 推送时提示认证失败

**A**: 使用 Personal Access Token 代替密码
- 访问 https://github.com/settings/tokens
- 生成新 token，勾选 `repo` 权限
- 使用 token 作为密码

### Q: 插件市场解析失败

**A**: 检查 metadata.yaml 格式
- 确保 YAML 语法正确
- 所有必填字段都存在
- repo 地址正确

### Q: 插件大小超过限制

**A**: 优化插件大小
- 检查 `.gitignore` 是否正确
- 移除不必要的文件
- 考虑外部依赖

### Q: 如何撤回已发布的插件

**A**: 联系 AstrBot 维护团队
- 通过官方渠道联系
- 说明撤回原因

## 📞 获取帮助

- **AstrBot 文档**: https://docs.astrbot.app
- **插件发布规范**: https://docs.astrbot.app/dev/star/plugin-publish.html
- **GitHub 帮助**: https://docs.github.com
- **社区支持**: AstrBot 官方群组

## ✅ 快速检查清单

发布前确认：

- [ ] 代码已提交到 Git
- [ ] 已创建 GitHub 仓库
- [ ] 代码已推送到 GitHub
- [ ] metadata.yaml 的 repo 字段正确
- [ ] 插件大小 < 16MB
- [ ] README.md 完整
- [ ] 已创建 GitHub Release（可选）
- [ ] 准备好发布到插件市场

---

**祝发布顺利！** 🎉

如有问题，请参考 [AstrBot 官方文档](https://docs.astrbot.app) 或提交 Issue。
