import { useEffect, useState } from 'react'
import type { ProjectSummary } from '../api/types'
import { errorMessage } from '../api/errors'
import { useUpdateProject } from '../query/projects'
import Modal from './ui/Modal'
import Button from './ui/Button'
import Input from './ui/Input'

interface ProjectEditModalProps {
  open: boolean
  project: ProjectSummary | null
  onClose: () => void
  onSaved?: (name: string) => void
}

/**
 * ★ 编辑项目资料（`B164` 改写）
 *
 * ⚠★ 与旧项目的差别：
 * - ❌ **删掉「分类」与「图标名」两个输入** —— ★ 新后端**没有** `category` / `icon` 字段
 * - ★★ `project.key` ⇒ **`project.project_ref`**
 * - ★ 保存走 **PATCH**（★ 旧站的 PUT 在新后端会 **405**）
 *
 * ★ 「公开 / 私有」不在这里改 —— ★ 它有自己的开关（★ 见 `ProjectCard` 的图标按钮），
 * ★ 因为那是个**有外部影响**的动作（⚠ 值得一次确认，而不是混在表单里随手保存）。
 */
export default function ProjectEditModal({ open, project, onClose, onSaved }: ProjectEditModalProps) {
  const [name, setName] = useState('')
  const [desc, setDesc] = useState('')
  const [error, setError] = useState('')
  const update = useUpdateProject(project?.project_ref || '')

  // ★ 打开时用当前项目值回填，关闭时清空错误
  useEffect(() => {
    if (!open || !project) return
    setName(project.name || '')
    setDesc(project.desc || '')
    setError('')
  }, [open, project])

  const submit = async () => {
    if (!name.trim()) {
      setError('项目名称不能为空')
      return
    }
    setError('')
    const r = await update
      .mutateAsync({ name: name.trim(), desc })
      .catch((e) => {
        console.error('update project failed', e)
        return null
      })
    if (!r) {
      setError(errorMessage(update.error, '保存失败，请重试'))
      return
    }
    onSaved?.(r.name || name.trim())
    onClose()
  }

  return (
    <Modal
      open={open}
      title="编辑项目"
      width={420}
      onClose={onClose}
      footer={
        <>
          <Button onClick={onClose}>取消</Button>
          <Button variant="primary" loading={update.isPending} onClick={submit}>保存</Button>
        </>
      }
    >
      <Input
        id="edit-proj-name"
        label="项目名称"
        value={name}
        maxLength={200}
        onChange={(e) => setName(e.target.value)}
        autoFocus
      />
      <Input
        id="edit-proj-desc"
        label="简介"
        value={desc}
        maxLength={2000}
        placeholder="一句话说明这个项目是做什么的"
        onChange={(e) => setDesc(e.target.value)}
      />
      {error && <div className="text-xs -mt-1" style={{ color: 'var(--err)' }}>{error}</div>}
    </Modal>
  )
}
