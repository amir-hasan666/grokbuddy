# Artifact Storage 与元数据

V1 本地文件系统 + Hub 元数据；未来 Git Artifact 或对象存储实现 ArtifactStore Port。类型：PLAN、FINAL_PACKAGE、DIFF、TEST_RESULT、SOURCE_FILE、SQL、REPORT、REVIEW_RESULT、EVIDENCE、LOG。

元数据必填：artifact_id、task_id、artifact_type、mime_type、storage_type、storage_pointer、sha256、size_bytes、created_by、created_at。sha256=原始 bytes 的 SHA-256；禁止对文本换行/编码隐式规范化后仍复用旧 hash。别名 content_hash/size 不另存可写字段。

本地内容地址布局为 `var/artifacts/sha256/<前两位>/<完整hash>`（设计路径）；数据库 pointer 为受控相对路径，不接受用户任意文件路径。写入 staging、计算 hash、原子 rename、事务提交元数据；同内容去重不改变任务级权限。大小上限默认 50 MiB，GitHub 控制消息上限 4096 UTF-8 bytes，是本项目设计限额而非声称 GitHub 平台限额。

Git 存储需记录 repository immutable ID + 完整 commit SHA + path + sha256，不能用可移动 branch HEAD 当审核证据。PR 只是 locator，审查必须固定 commit 和路径。对象存储记录 object version/hash；鉴权 URL 不作为长期 pointer。

## Final Package

manifest 必须关联原始任务 artifact、批准的 plan/hash、变更范围、文件列表、commit SHA 或 diff artifact、自检结论、测试结果 artifact、已知风险、未验证事项、review_profile/version/hash、content_revision。每个引用有 id/hash，缺产物或 hash 不符拒绝发起最终审核。

本地路径不可由 Grok 云端直接读。真实接入前必须通过测试选择：不可变 Git 文件（先脱敏，独立 Reviewer 可读），或 Hub 的受认证下载服务（公网/安全隧道且有 scope）。两者目前只是方案，没有上传任何工作材料。

## Comment 指针

```text
[AI-COLLAB v1]
protocol_version=v1
type=FINAL_REVIEW
task_id=TASK-<uuid>
review_request_id=RR-<uuid>
review_id=REV-<uuid>
round=1
artifact_id=ART-<uuid>
artifact_sha256=<64 lowercase hex>
artifact_pointer=hub-artifact:ART-<uuid>
summary=请审核冻结的交付包
```

`hub-artifact:` 是本项目内部逻辑指针，不是可公网访问 URL，不声称 Grok 原生认识该协议。Reviewer 需要经验证的 artifact fetch 适配；可附经过注册的 Git commit/path/URL metadata。结果用 AI-REVIEW v1 指向 REVIEW_RESULT artifact，原始 JSON 不贴 Comment。

## 保留与清理

默认终结任务后至少保留 180 天；任何 active task、review/finding evidence、未到期审批、legal hold、审计引用仍 pin 的内容均不清理。清理先做 dry-run 清单 → 引用检查 → 人工批准 → 标记待清理 → 隔离宽限 7 天 → 再检查 → 删除 bytes，保留 tombstone 元数据与 hash/Audit。生产删除始终遵循 Human Approval。

失败上传的孤儿暂存对象可在本地开发过期清理，但不碰已注册引用对象。DB 和 content store 恢复须同 manifest 验证。已丢失/被篡改 Artifact 标记不可用，相关 Review 不得假装证据仍可读。
