// src/components/playground/ChatArea/ChatInput/ChatInput.tsx
'use client'
import { useState, useRef } from 'react'
import { toast } from 'sonner'
import { TextArea } from '@/components/ui/textarea'
import { Button } from '@/components/ui/button'
import { usePlaygroundStore } from '@/store'
import useAIChatStreamHandler from '@/hooks/useAIStreamHandler'
import { useQueryState } from 'nuqs'
import Icon from '@/components/ui/icon'
import type { PlaygroundChatMessage } from '@/types/playground'

// --- helpers (typed) ---
const now = () => Date.now()
const makeMsg = (
  role: PlaygroundChatMessage['role'],
  content = ''
): PlaygroundChatMessage => ({
  role,
  content,
  created_at: now()
})

const ChatInput = () => {
  const { chatInputRef } = usePlaygroundStore()
  const setMessages    = usePlaygroundStore((s) => s.setMessages)
  const isStreaming    = usePlaygroundStore((s) => s.isStreaming)
  const setIsStreaming = usePlaygroundStore((s) => s.setIsStreaming)

  const fileInputRef = useRef<HTMLInputElement>(null)
  const { handleStreamResponse } = useAIChatStreamHandler()
  const [selectedAgent] = useQueryState('agent')
  const [inputMessage, setInputMessage] = useState('')

  const base = usePlaygroundStore.getState().selectedEndpoint || ''

  const handleSubmit = async () => {
    if (!inputMessage.trim()) return
    const currentMessage = inputMessage
    setInputMessage('')
    try {
      await handleStreamResponse(currentMessage)
    } catch (error) {
      toast.error(
        `Error in handleSubmit: ${error instanceof Error ? error.message : String(error)}`
      )
    }
  }

  const handleUploadClick = () => fileInputRef.current?.click()

  const handleFileSelected: React.ChangeEventHandler<HTMLInputElement> = async (e) => {
    const file = e.target.files?.[0]
    if (!file) return

    // Build /upload from endpoint origin (works with/without /v1)
    const endpointURL = new URL(base || 'http://127.0.0.1:7777/v1')
    const uploadUrl   = `${endpointURL.origin}/upload`

    try {
      const form = new FormData()
      form.append('file', file)

      // 1) push user message + EMPTY agent placeholder (triggers loader)
      const userMsg        = makeMsg('user',  `Uploaded file: ${file.name}`)
      const placeholderMsg = makeMsg('agent', '') // empty => shows AgentThinkingLoader
      setMessages((prev) => [...prev, userMsg, placeholderMsg])

      setIsStreaming(true)

      // 2) call backend
      const res  = await fetch(uploadUrl, { method: 'POST', body: form })
      if (!res.ok) throw new Error(await res.text())
      const data: { ok: boolean; summary?: string } = await res.json()
      if (!data.ok) throw new Error('Upload failed')

      const summaryMsg = makeMsg('agent', data.summary ?? 'Processed.')

      // 3) replace the MOST-RECENT EMPTY agent message with the summary
      setMessages((prev) => {
        const out = [...prev]
        let replaced = false
        for (let i = out.length - 1; i >= 0; i--) {
          const m = out[i]
          if (m.role === 'agent' && (!m.content || m.content === '')) {
            out[i] = { ...summaryMsg, created_at: now() }
            replaced = true
            break
          }
        }
        if (!replaced) out.push(summaryMsg)
        return out
      })

      toast.success('File processed successfully')
    } catch (err) {
      const errorMsg = makeMsg(
        'agent',
        `Upload failed: ${err instanceof Error ? err.message : String(err)}`
      )
      setMessages((prev) => {
        const out = [...prev]
        // Try to replace the pending placeholder if it exists
        for (let i = out.length - 1; i >= 0; i--) {
          const m = out[i]
          if (m.role === 'agent' && (!m.content || m.content === '')) {
            out[i] = errorMsg
            return out
          }
        }
        // Otherwise append the error
        return [...out, errorMsg]
      })
    } finally {
      setIsStreaming(false)
      if (fileInputRef.current) fileInputRef.current.value = ''
    }
  }

  return (
    <div className="relative mx-auto mb-1 flex w-full max-w-2xl items-end justify-center gap-x-2 font-geist">
      <TextArea
        placeholder="Ask anything"
        value={inputMessage}
        onChange={(e) => setInputMessage(e.target.value)}
        onKeyDown={(e) => {
          if (e.key === 'Enter' && !e.nativeEvent.isComposing && !e.shiftKey && !isStreaming) {
            e.preventDefault()
            handleSubmit()
          }
        }}
        className="w-full border border-accent bg-primaryAccent px-4 text-sm text-primary focus:border-accent"
        disabled={!selectedAgent || isStreaming}
        ref={chatInputRef}
      />
      <Button
        onClick={handleSubmit}
        disabled={!selectedAgent || !inputMessage.trim() || isStreaming}
        size="icon"
        className="rounded-xl bg-primary p-5 text-primaryAccent"
        title={isStreaming ? 'Busy…' : 'Send'}
      >
        <Icon type="send" color="primaryAccent" />
      </Button>

      <input
        type="file"
        accept=".json,.xml,.csv,.zip,.rar"
        ref={fileInputRef}
        onChange={handleFileSelected}
        className="hidden"
      />
      <Button
        type="button"
        onClick={handleUploadClick}
        disabled={!selectedAgent || isStreaming}
        size="icon"
        className="rounded-xl bg-primary p-5 text-primaryAccent"
        title="Upload file"
      >
        <Icon type="download" color="primaryAccent" />
      </Button>
    </div>
  )
}

export default ChatInput
