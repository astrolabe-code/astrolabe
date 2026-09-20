import { useEffect, useState } from 'react'
import { GitBranch } from 'lucide-react'
import { useCreateProject } from '../query/projects'
import { errorMessage } from '../api/errors'
import Modal from './ui/Modal'
import Button from './ui/Button'
import Input from './ui/Input'

interface ProjectCreateModalProps {
  open: boolean
  onClose: () => void
  /** ★ 创建成功后回调，由页面负责跳转 */
  onCreated: (projectRef: string) => void
}

/**
 * ★ 新建项目（`B164` 重做）
 *
 * ## ⚠★★ 为什么必须重做 —— 入参完全不同
 *
 * | | 旧站 | ★★ 新后端（`views/projects.py::_create`） |
 * |---|---|---|
 * | 名称 | ✅ | ✅ |
 * | ★★ **仓库地址** | ❌ 没这个概念 | ★★★ **必填** —— 缺则 `400 missing_fields` |
 * | ★★★ **托管平台** | ❌ | ★★★ **必填** —— 必须是 `github` / `gitee`，★ 否则 `400 invalid_provider` |
 * | commit | ❌ | ★ 可选（★ 缺省 = HEAD） |
 * | ★ 公开 | ❌ | ★ 可选（★ 默认私有） |
 * | ⚠ 分类 / 图标 | ✅ | ❌ **新后端没有这两个字段** |
 *
 * ★★★ **为什么仓库地址是必填**：★ `B109` —— **源码只能由服务端拉取**
 *（❌ 不接受用户上传 zip）⇒ ★ **没有仓库地址就无从解析**。
 *
 * ## ⚠ 另一处改动：**删掉了"第二步：上传源码"**
 *
 * ★ 旧版是「信息 → 上传 zip」两步；★ 新设计没有 zip 这条路
 * ⇒ ★★ 创建完**直接进项目页**（★ 在那里触发解析）。
 */
export default function ProjectCreateModal({ open, onClose, onCreated }: ProjectCreateModalProps) {
  const [name, setName] = useState('')
  const [repoUrl, setRepoUrl] = useState('')
  const [provider, setProvider] = useState<'github' | 'gitee'>('github')
  const [commit, setCommit] = useState('')
  const [desc, setDesc] = useState('')
  const [isPublic, setIsPublic] = useState(false)
  const [error, setError] = useState('')
  const create = useCreateProject()

  // ★ 每次关闭后重置表单，避免上次残留
  useEffect(() => {
    if (open) return
    setName('')
    setRepoUrl('')
    setProvider('github')
    setCommit('')
    setDesc('')
    setIsPublic(false)
    setError('')
  }, [open])

  const submit = async () => {
    if (!name.trim()) {
      setError('请填写项目名称')
      return
    }
    if (!repoUrl.trim()) {
      setError('请填写仓库地址（★ 源码由服务端从仓库拉取）')
      return
    }
    setError('')
    const r = await create
      .mutateAsync({
        name: name.trim(),
        repo_url: repoUrl.trim(),
        provider,
        commit: commit.trim() || undefined,
        desc,
        is_public: isPublic,
      })
      .catch((e) => {
        console.error('create project failed', e)
        return null
      })
    if (!r) {
      setError(errorMessage(create.error, '创建失败，请重试'))
      return
    }
    onCreated(r.project_ref)
  }

  return (
    <Modal
      open={open}
      title="新建项目"
      width={460}
      onClose={onClose}
      footer={
        <>
          <Button onClick={onClose}>取消</Button>
          <Button variant="primary" loading={create.isPending} onClick={submit}>
            {create.isPending ? '创建中…' : '创建'}
          </Button>
        </>
      }
    >
      <>
        <Input
          id="proj-name"
          label="项目名称"
          value={name}
          maxLength={200}
          placeholder="例如：小型 Redis 克隆"
          onChange={(e) => setName(e.target.value)}
          autoFocus
        />

        {/* ★★ 托管平台 —— 必填（B109：源码只能服务端拉取） */}
        <div className="mb-3">
          <label className="block text-xs mb-1.5 text-text-sub">托管平台</label>
          <div className="flex gap-2">
            {(['github', 'gitee'] as const).map((p) => (
              <button
                key={p}
                type="button"
                className={`btn ${provider === p ? 'primary' : 'ghost'}`}
                style={{ flex: 1, justifyContent: 'center' }}
                onClick={() => setProvider(p)}
              >
                <GitBranch size={14} />
                {p === 'github' ? 'GitHub' : 'Gitee'}
              </button>
            ))}
          </div>
        </div>

        <Input
          id="proj-repo"
          label="仓库地址"
          value={repoUrl}
          maxLength={512}
          placeholder="https://github.com/owner/repo"
          hint="★ 源码由服务端从这个仓库拉取（本平台不接受上传压缩包）"
          onChange={(e) => setRepoUrl(e.target.value)}
        />
        <Input
          id="proj-commit"
          label="commit（可选）"
          value={commit}
          maxLength={64}
          placeholder="留空 = 默认分支最新提交"
          hint="★ 填了就会拉取该提交 —— 图会锚定到它"
          onChange={(e) => setCommit(e.target.value)}
        />
        <Input
          id="proj-desc"
          label="简介"
          value={desc}
          maxLength={2000}
          placeholder="一句话说明这个项目是做什么的"
          onChange={(e) => setDesc(e.target.value)}
        />

        <label className="flex items-center gap-2 text-xs text-text-sub" style={{ cursor: 'pointer' }}>
          <input type="checkbox" checked={isPublic} onChange={(e) => setIsPublic(e.target.checked)} />
          创建后立即公开（★ 游客也能浏览）
        </label>

        {error && <div className="text-xs mt-2" style={{ color: 'var(--err)' }}>{error}</div>}
      </>
    </Modal>
  )
}
