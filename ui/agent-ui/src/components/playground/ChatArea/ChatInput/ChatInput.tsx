'use client'
import { useState, useRef } from 'react' 
import { toast } from 'sonner'
import { TextArea } from '@/components/ui/textarea'
import { Button } from '@/components/ui/button'
import { usePlaygroundStore } from '@/store'
import useAIChatStreamHandler from '@/hooks/useAIStreamHandler'
import { useQueryState } from 'nuqs'
import Icon from '@/components/ui/icon'


const ChatInput = () => {
  const { chatInputRef } = usePlaygroundStore()
  const fileInputRef = useRef<HTMLInputElement>(null)
  const { handleStreamResponse } = useAIChatStreamHandler()
  const [selectedAgent] = useQueryState('agent')
  const [inputMessage, setInputMessage] = useState('')
  const isStreaming = usePlaygroundStore((state) => state.isStreaming)
  const handleSubmit = async () => {
    if (!inputMessage.trim()) return

    const currentMessage = inputMessage
    setInputMessage('')

    try {
      await handleStreamResponse(currentMessage)
    } catch (error) {
      toast.error(
        `Error in handleSubmit: ${
          error instanceof Error ? error.message : String(error)
        }`
      )
    }
  }
  const handleUploadClick = () => fileInputRef.current?.click()

  const handleFileSelected: React.ChangeEventHandler<HTMLInputElement> = async (e) => {
    const file = e.target.files?.[0]
    if (!file) return
    try {
      const form = new FormData()
      form.append('file', file)
      // IMPORTANT: This is the playground endpoint you started with `python playground.py`
      const endpoint = 'http://localhost:7777/upload'
      const res = await fetch(endpoint, {
        method: 'POST',
        body: form
      })
      if (!res.ok) throw new Error(await res.text())
      const json = await res.json()

      // Display result in the chat UI (user-friendly)
      addMessage({
        role: 'user',
        content: `Uploaded file: ${file.name}`
      })
      addMessage({
        role: 'assistant',
        content: '```json\n' + JSON.stringify(json, null, 2) + '\n```'
      })
      toast.success('File processed successfully')
    } catch (err) {
      toast.error(`Upload failed: ${err instanceof Error ? err.message : String(err)}`)
    } finally {
      if (fileInputRef.current) fileInputRef.current.value = ''
    }
  }
  return (
    <div className="relative mx-auto mb-1 flex w-full max-w-2xl items-end justify-center gap-x-2 font-geist">
      <TextArea
        placeholder={'Ask anything'}
        value={inputMessage}
        onChange={(e) => setInputMessage(e.target.value)}
        onKeyDown={(e) => {
          if (
            e.key === 'Enter' &&
            !e.nativeEvent.isComposing &&
            !e.shiftKey &&
            !isStreaming
          ) {
            e.preventDefault()
            handleSubmit()
          }
        }}
        className="w-full border border-accent bg-primaryAccent px-4 text-sm text-primary focus:border-accent"
        disabled={!selectedAgent}
        ref={chatInputRef}
      />
      <Button
        onClick={handleSubmit}
        disabled={!selectedAgent || !inputMessage.trim() || isStreaming}
        size="icon"
        className="rounded-xl bg-primary p-5 text-primaryAccent"
      >
        <Icon type="send" color="primaryAccent" />
      </Button>
      <input
        type="file"
        accept=".json,.xml,.csv,.zip"
        ref={fileInputRef}
        onChange={handleFileSelected}
        className="hidden"
      />
      <Button
        type="button"
        onClick={handleUploadClick}
        size="icon"
        className="rounded-xl bg-primary p-5 text-primaryAccent"
        title="Upload file"
      >
        <Icon type="download" color="primaryAccent"/>
      </Button>
    </div>
  )
}

export default ChatInput
