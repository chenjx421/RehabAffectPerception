# Demo2 内测账号交付单

本文件仅用于本地演示和首次学校内测，不应随公开材料发布。部署到局域网或云端前，应重新初始化账号密码并通过独立渠道交付。

2026-09-08 已简化账号别名，并单独更新了本机密码。密码见本机私有文件 [.runtime/demo2_pilot_accounts_20260908.md](D:/GIT/RehabAffectPerception/.runtime/demo2_pilot_accounts_20260908.md)，该文件不进入版本库和页面预览包。

| 用途 | 登录账号 | 保留的原账号 | 绑定范围 |
| --- | --- | --- | --- |
| 学校上传账号 1 | `t1` | `school_uploader_01` | `channel_1` |
| 学校上传账号 2 | `t2` | `school_uploader_02` | `channel_2` |
| 学校上传账号 3 | `t3` | `school_uploader_03` | `channel_3` |
| 学校上传账号 4 | `t4` | `school_uploader_04` | `channel_4` |
| 公司管理后台 | `admin` | `company_admin` | 查看 4 个通道汇总 |

## 使用入口

1. 双击项目根目录的 `start_school_demo2.cmd`。
2. 浏览器打开 `http://127.0.0.1:8791/demo2/login`。
3. 用户身份登录后先进入 `/demo2/school` 确认城市、区县、学校，再进入 `/demo2/upload`。
4. 公司管理账号登录后进入 `/demo2/admin`。

## 交付规则

- 会员注册页 `/demo2/register` 可以提交开通申请，申请进入管理员后台；不自动创建可用账号。
- 每个学校账号固定绑定一个视频通道，不能查看或操作其他通道。
- 每个账号在同一课程 ID 下默认可上传 5 段视频。
- 上传前必须确认校方授权；公司长期保存仅限另行授权的脱敏结构化结果，不默认长期保存原视频。
- 本地默认密码只适合演示。云端部署必须使用随机强密码、HTTPS、账号重置和更完整的安全审计。
