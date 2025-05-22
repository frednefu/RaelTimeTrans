# 实时翻译项目 Git 使用指南

本文档提供了如何使用Git来管理实时翻译项目代码的指南。

## 基本Git操作

### 查看当前状态

```bash
git status
```

### 查看修改历史

```bash
git log
```

### 添加文件到暂存区

```bash
# 添加单个文件
git add 文件名

# 添加所有修改的文件
git add .
```

### 提交更改

```bash
git commit -m "提交说明"
```

### 拉取远程更新

```bash
git pull origin 分支名称
```

### 推送到远程仓库

```bash
git push origin 分支名称
```

## 分支管理

### 创建新分支

```bash
git branch 分支名称
```

### 切换分支

```bash
git checkout 分支名称
```

### 创建并切换分支

```bash
git checkout -b 分支名称
```

### 合并分支

```bash
# 切换到目标分支
git checkout 目标分支

# 合并源分支到当前分支
git merge 源分支
```

## 项目开发工作流

1. **功能开发**：
   - 创建新分支 `git checkout -b feature/功能名称`
   - 在分支上开发并提交
   - 完成后合并到主分支

2. **Bug修复**：
   - 创建修复分支 `git checkout -b bugfix/问题描述`
   - 修复问题并提交
   - 合并回主分支

3. **版本发布**：
   - 创建版本标签 `git tag -a v1.0.0 -m "版本说明"`
   - 推送标签 `git push origin --tags`

## Git提交规范

为保持提交记录的清晰和一致性，请遵循以下提交消息格式：

- `feat`: 新功能
- `fix`: 修复bug
- `docs`: 文档更新
- `style`: 代码格式修改
- `refactor`: 代码重构
- `test`: 添加测试
- `chore`: 构建过程或辅助工具的变动

示例：`fix: 修复字幕显示闪烁问题`

## 忽略文件配置

本项目的.gitignore文件已配置为忽略以下内容：

- Python编译文件`__pycache__/`和`*.pyc`
- 个人设置文件`settings.json`和`settings_backup.json`
- 日志文件`*.log`
- Whisper模型缓存
- 用户生成的字幕文件

如需忽略其他文件，请编辑`.gitignore`文件。

## 远程仓库设置

### 添加远程仓库

```bash
git remote add origin 远程仓库URL
```

### 查看远程仓库

```bash
git remote -v
```

### 首次推送到远程仓库

```bash
git push -u origin master
```

## 常见问题解决

1. **合并冲突**：
   - 使用`git status`查看冲突文件
   - 手动编辑解决冲突
   - 解决后`git add .`标记为已解决
   - 使用`git commit`完成合并

2. **撤销修改**：
   - 撤销工作区修改：`git checkout -- 文件名`
   - 撤销暂存区修改：`git reset HEAD 文件名`
   - 撤销最近一次提交：`git reset --soft HEAD^` 

## 处理大文件和 GitHub 上传

### GitHub 文件大小限制

GitHub 对单个文件的大小限制为 100MB。如果遇到大文件上传问题，请按以下步骤处理：

1. **检查大文件**
```bash
# 查看仓库中最大的文件
git rev-list --objects --all | git cat-file --batch-check='%(objecttype) %(objectname) %(objectsize) %(rest)' | sort -k3nr | head -n 10
```

2. **从 Git 历史中删除大文件**
```bash
# 从 Git 历史中删除指定文件
git filter-branch --force --index-filter "git rm --cached --ignore-unmatch 文件路径" --prune-empty --tag-name-filter cat -- --all
```

3. **强制推送更新后的历史**
```bash
git push origin main --force
```

### 处理大文件的最佳实践

1. **使用 .gitignore**
   - 在 `.gitignore` 文件中添加大文件目录
   - 例如：`ffmpeg_temp/` 目录已被配置为忽略

2. **替代方案**
   - 将大文件存储在外部存储服务中
   - 在安装脚本中自动下载所需的大文件
   - 使用 Git LFS（Large File Storage）管理大文件

3. **项目配置**
   - 确保 `.gitignore` 文件包含所有需要忽略的大文件
   - 在 README 中说明如何获取和安装大文件
   - 提供自动下载脚本

### 常见错误及解决方案

1. **错误：文件超过 GitHub 大小限制**
```
remote: error: File xxx is 127.43 MB; this exceeds GitHub's file size limit of 100.00 MB
```
解决方案：
- 从 Git 历史中删除该文件
- 使用上述 `git filter-branch` 命令清理历史
- 强制推送更新后的历史

2. **错误：推送被拒绝**
```
! [remote rejected] main -> main (pre-receive hook declined)
```
解决方案：
- 检查是否有大文件
- 清理 Git 历史
- 使用 `--force` 选项推送

3. **错误：无法删除文件**
```
fatal: pathspec 'xxx' did not match any files
```
解决方案：
- 确认文件路径是否正确
- 使用 `git ls-files` 查看所有被跟踪的文件
- 确保文件确实存在于 Git 历史中 