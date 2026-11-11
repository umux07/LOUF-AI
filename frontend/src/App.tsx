import { useCallback, useEffect, useRef, useState } from 'react'
import type { FormEvent } from 'react'
import ReactMarkdown from 'react-markdown'
import remarkGfm from 'remark-gfm'
import {
  Activity, ArrowUp, Check, ChevronDown, CircleHelp, Copy, GalleryVerticalEnd,
  Image, LoaderCircle, LogOut, Menu, MessageSquarePlus, MoreHorizontal, Pencil, Plus,
  Search, Settings, ShieldCheck, Sparkles, Trash2, Video, X,
} from 'lucide-react'
import './App.css'

const API = '/api/v1'

type User = { id: string; email: string; role: string; is_guest: boolean; created_at: string }
type Conversation = { id: string; title: string; created_at: string; updated_at: string }
type Message = { id: string; role: 'user' | 'assistant'; content: string; model?: string | null }
type ModelStatus = { connected: boolean; provider: string; models: { name: string; size: number | null }[]; message: string | null }
type MediaJob = {
  id: string
  media_type: 'image' | 'video'
  prompt: string
  status: 'queued' | 'processing' | 'completed' | 'failed'
  error: string | null
  created_at: string
  file_url: string | null
}
type Capabilities = {
  images: { available: boolean; message: string; provider: string }
  videos: { available: boolean; message: string; provider: string }
}
type Section = 'chat' | 'images' | 'videos' | 'gallery' | 'settings'

async function csrfToken() {
  const response = await fetch(`${API}/auth/csrf`, { credentials: 'include' })
  if (!response.ok) throw new Error('Could not initialize a secure session. Refresh and try again.')
  const result = (await response.json()) as { csrf_token: string }
  return result.csrf_token
}

async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const method = (init.method ?? 'GET').toUpperCase()
  const headers = new Headers(init.headers)
  if (init.body) headers.set('Content-Type', 'application/json')
  if (!['GET', 'HEAD', 'OPTIONS'].includes(method)) headers.set('X-CSRF-Token', await csrfToken())
  const response = await fetch(`${API}${path}`, { ...init, headers, credentials: 'include' })
  if (!response.ok) {
    const body = (await response.json().catch(() => ({}))) as { detail?: string }
    throw new Error(body.detail ?? `Request failed (${response.status}).`)
  }
  if (response.status === 204) return undefined as T
  return (await response.json()) as T
}

function App() {
  const [user, setUser] = useState<User | null>(null)
  const [authReady, setAuthReady] = useState(false)
  const [registering, setRegistering] = useState(false)
  const [forgotPassword, setForgotPassword] = useState(false)
  const [resetToken, setResetToken] = useState(() => new URLSearchParams(window.location.hash.slice(1)).get('reset_token') ?? '')
  const [authError, setAuthError] = useState('')
  const [authNotice, setAuthNotice] = useState('')
  const [busy, setBusy] = useState(false)
  const [email, setEmail] = useState('')
  const [password, setPassword] = useState('')
  const [section, setSection] = useState<Section>('chat')
  const [mobileOpen, setMobileOpen] = useState(false)
  const [conversations, setConversations] = useState<Conversation[]>([])
  const [selectedId, setSelectedId] = useState<string | null>(null)
  const [messages, setMessages] = useState<Message[]>([])
  const [models, setModels] = useState<ModelStatus | null>(null)
  const [capabilities, setCapabilities] = useState<Capabilities | null>(null)
  const [mediaJobs, setMediaJobs] = useState<MediaJob[]>([])
  const [selectedModel, setSelectedModel] = useState('')
  const [prompt, setPrompt] = useState('')
  const [imagePrompt, setImagePrompt] = useState('')
  const [videoPrompt, setVideoPrompt] = useState('')
  const [search, setSearch] = useState('')
  const [loadingMessages, setLoadingMessages] = useState(false)
  const [sending, setSending] = useState(false)
  const [appError, setAppError] = useState('')
  const [dark, setDark] = useState(() => localStorage.getItem('louf-theme') === 'dark')
  const [copiedId, setCopiedId] = useState('')
  const [renamingId, setRenamingId] = useState<string | null>(null)
  const [renameTitle, setRenameTitle] = useState('')
  const endRef = useRef<HTMLDivElement>(null)
  const promptRef = useRef<HTMLTextAreaElement>(null)
  const activeRequest = useRef<AbortController | null>(null)
  const responseText = useRef('')
  const skipMessageReload = useRef<string | null>(null)

  const refreshModels = useCallback(async () => {
    const status = await api<ModelStatus>('/models')
    setModels(status)
    if (!selectedModel && status.models.length) setSelectedModel(status.models[0].name)
  }, [selectedModel])

  const refreshConversations = useCallback(async () => {
    const rows = await api<Conversation[]>('/conversations')
    setConversations(rows)
    return rows
  }, [])

  const refreshMediaJob = useCallback(async (id: string) => {
    const updated = await api<MediaJob>(`/media/jobs/${id}`)
    setMediaJobs((jobs) => jobs.map((job) => job.id === id ? updated : job))
    return updated
  }, [])

  useEffect(() => {
    document.documentElement.dataset.theme = dark ? 'dark' : 'light'
    localStorage.setItem('louf-theme', dark ? 'dark' : 'light')
  }, [dark])

  useEffect(() => {
    api<User>('/users/me')
      .then(setUser)
      .catch(() => setUser(null))
      .finally(() => setAuthReady(true))
  }, [])

  useEffect(() => {
    if (!user) return
    let active = true
    async function loadWorkspace() {
      try {
        const [rows, status, available, generatedMedia] = await Promise.all([
          api<Conversation[]>('/conversations'),
          api<ModelStatus>('/models'),
          api<Capabilities>('/capabilities'),
          api<MediaJob[]>('/media/jobs'),
        ])
        if (!active) return
        setConversations(rows)
        setModels(status)
        setSelectedModel((current) => current || status.models[0]?.name || '')
        setCapabilities(available)
        setMediaJobs(generatedMedia)
      } catch (error) {
        if (active) setAppError((error as Error).message)
      }
    }
    void loadWorkspace()
    return () => { active = false }
  }, [user])

  useEffect(() => {
    if (!user || !mediaJobs.some((job) => job.status === 'queued' || job.status === 'processing')) return
    let active = true
    const poll = async () => {
      const pending = mediaJobs.filter((job) => job.status === 'queued' || job.status === 'processing')
      const results = await Promise.allSettled(pending.map((job) => refreshMediaJob(job.id)))
      if (active) {
        const failed = results.find((result): result is PromiseRejectedResult => result.status === 'rejected')
        if (failed) setAppError((failed.reason as Error).message)
      }
    }
    const timer = window.setInterval(() => { void poll() }, 2500)
    return () => {
      active = false
      window.clearInterval(timer)
    }
  }, [mediaJobs, refreshMediaJob, user])

  useEffect(() => endRef.current?.scrollIntoView({ behavior: 'smooth' }), [messages, sending])

  useEffect(() => {
    if (!user || !selectedId) return
    if (skipMessageReload.current === selectedId) {
      skipMessageReload.current = null
      return
    }
    setLoadingMessages(true)
    api<Message[]>(`/conversations/${selectedId}/messages`)
      .then(setMessages)
      .catch((error: Error) => setAppError(error.message))
      .finally(() => setLoadingMessages(false))
  }, [selectedId, user])

  async function submitAuth(event: FormEvent) {
    event.preventDefault()
    setBusy(true)
    setAuthError('')
    setAuthNotice('')
    try {
      if (resetToken) {
        const result = await api<{ message: string }>('/auth/password-reset/confirm', {
          method: 'POST',
          body: JSON.stringify({ token: resetToken, password }),
        })
        setResetToken('')
        window.history.replaceState({}, '', window.location.pathname + window.location.search)
        setPassword('')
        setAuthNotice(result.message)
      } else if (forgotPassword) {
        const result = await api<{ message: string }>('/auth/password-reset/request', {
          method: 'POST',
          body: JSON.stringify({ email }),
        })
        setAuthNotice(result.message)
      } else {
        const endpoint = registering ? '/auth/register' : '/auth/login'
        const result = await api<User>(endpoint, {
          method: 'POST',
          body: JSON.stringify({ email, password }),
        })
        setUser(result)
      }
    } catch (error) {
      setAuthError((error as Error).message)
    } finally {
      setBusy(false)
    }
  }

  async function continueAsGuest() {
    setBusy(true)
    setAuthError('')
    try {
      setUser(await api<User>('/auth/guest', { method: 'POST' }))
    } catch (error) {
      setAuthError((error as Error).message)
    } finally {
      setBusy(false)
    }
  }

  async function saveConversationTitle(event: FormEvent, id: string) {
    event.preventDefault()
    const title = renameTitle.trim()
    if (!title) return
    try {
      const updated = await api<Conversation>(`/conversations/${id}`, {
        method: 'PATCH',
        body: JSON.stringify({ title }),
      })
      setConversations((rows) => rows.map((item) => item.id === id ? updated : item))
      setRenamingId(null)
    } catch (error) {
      setAppError((error as Error).message)
    }
  }

  async function createConversation() {
    setAppError('')
    try {
      setMessages([])
      const conversation = await api<Conversation>('/conversations', {
        method: 'POST',
        body: JSON.stringify({ title: 'New conversation' }),
      })
      setConversations((rows) => [conversation, ...rows])
      skipMessageReload.current = conversation.id
      setSelectedId(conversation.id)
      setSection('chat')
      setMobileOpen(false)
      promptRef.current?.focus()
    } catch (error) {
      setAppError((error as Error).message)
    }
  }

  async function removeConversation(id: string) {
    if (!window.confirm('Delete this conversation and its messages? This cannot be undone.')) return
    try {
      await api(`/conversations/${id}`, { method: 'DELETE' })
      const remaining = conversations.filter((item) => item.id !== id)
      setConversations(remaining)
      if (selectedId === id) {
        setSelectedId(remaining[0]?.id ?? null)
        setMessages([])
      }
    } catch (error) {
      setAppError((error as Error).message)
    }
  }

  async function sendMessage(event?: FormEvent, retryText?: string) {
    event?.preventDefault()
    const text = (retryText ?? prompt).trim()
    if (!text || sending) return
    if (!selectedModel) {
      setAppError('Connect Bionic and select an available model before sending a message.')
      return
    }
    setAppError('')
    let conversationId = selectedId
    try {
      if (!conversationId) {
        const created = await api<Conversation>('/conversations', {
          method: 'POST',
          body: JSON.stringify({ title: 'New conversation' }),
        })
        conversationId = created.id
        setConversations((rows) => [created, ...rows])
        skipMessageReload.current = created.id
        setSelectedId(created.id)
      }
      const userMessage: Message = { id: crypto.randomUUID(), role: 'user', content: text }
      const responseId = crypto.randomUUID()
      setMessages((rows) => [...rows, userMessage, { id: responseId, role: 'assistant', content: '' }])
      setPrompt('')
      setSending(true)
      const controller = new AbortController()
      activeRequest.current = controller
      const response = await fetch(`${API}/conversations/${conversationId}/messages`, {
        method: 'POST',
        credentials: 'include',
        signal: controller.signal,
        headers: { 'Content-Type': 'application/json', 'X-CSRF-Token': await csrfToken() },
        body: JSON.stringify({ prompt: text, model: selectedModel }),
      })
      if (!response.ok) {
        const body = (await response.json().catch(() => ({}))) as { detail?: string }
        throw new Error(body.detail ?? `Request failed (${response.status}).`)
      }
      if (!response.body) throw new Error('The server did not return a response stream.')
      const reader = response.body.getReader()
      const decoder = new TextDecoder()
      let pending = ''
      responseText.current = ''
      let streamError = ''
      let streamComplete = false
      while (true) {
        const { value, done } = await reader.read()
        if (done) break
        pending += decoder.decode(value, { stream: true })
        const events = pending.split('\n\n')
        pending = events.pop() ?? ''
        for (const raw of events) {
          const dataLine = raw.split('\n').find((line) => line.startsWith('data: '))
          if (!dataLine) continue
          const item = JSON.parse(dataLine.slice(6)) as { delta?: string; error?: string }
          if (item.error) streamError = item.error
          if ('done' in item && item.done) streamComplete = true
          if (item.delta) {
            responseText.current += item.delta
            setMessages((rows) =>
              rows.map((message) => message.id === responseId ? { ...message, content: responseText.current } : message),
            )
          }
        }
      }
      if (streamError) throw new Error(streamError)
      if (!streamComplete) throw new Error('The response stream ended before it was saved.')
      if (!responseText.current) throw new Error('The model returned an empty response.')
      await refreshConversations()
    } catch (error) {
      setMessages((rows) => rows.filter((item) => item.role !== 'assistant' || item.content))
      setAppError((error as Error).name === 'AbortError' ? 'Generation cancelled.' : (error as Error).message)
    } finally {
      activeRequest.current = null
      setSending(false)
    }
  }

  async function logout() {
    try {
      await api('/auth/logout', { method: 'POST' })
    } finally {
      setUser(null)
      setSelectedId(null)
      setConversations([])
      setMessages([])
      setMediaJobs([])
    }
  }

  async function generateMedia(event: FormEvent, mediaType: 'image' | 'video') {
    event.preventDefault()
    const text = (mediaType === 'image' ? imagePrompt : videoPrompt).trim()
    const available = mediaType === 'image' ? capabilities?.images.available : capabilities?.videos.available
    if (!text || !available) return
    setAppError('')
    try {
      const job = await api<MediaJob>('/media/jobs', {
        method: 'POST',
        body: JSON.stringify({ media_type: mediaType, prompt: text }),
      })
      setMediaJobs((jobs) => [job, ...jobs.filter((item) => item.id !== job.id)])
      if (mediaType === 'image') setImagePrompt('')
      else setVideoPrompt('')
    } catch (error) {
      setAppError((error as Error).message)
    }
  }

  async function deleteMediaJob(job: MediaJob) {
    if (!window.confirm('Delete this generated media and its job record? This cannot be undone.')) return
    try {
      await api(`/media/jobs/${job.id}`, { method: 'DELETE' })
      setMediaJobs((jobs) => jobs.filter((item) => item.id !== job.id))
    } catch (error) {
      setAppError((error as Error).message)
    }
  }

  async function copyMessage(message: Message) {
    await navigator.clipboard.writeText(message.content)
    setCopiedId(message.id)
    window.setTimeout(() => setCopiedId(''), 1400)
  }

  const visibleMediaJobs = section === 'gallery'
    ? mediaJobs
    : mediaJobs.filter((job) => job.media_type === (section === 'images' ? 'image' : 'video'))

  if (!authReady) return <div className="boot-screen"><Sparkles size={22} /> LOUF AI</div>

  if (!user || resetToken) {
    return (
      <main className="auth-screen">
        <div className="auth-art">
          <div className="auth-orb orb-one" /><div className="auth-orb orb-two" />
          <div className="auth-copy">
            <div className="brand-mark"><Sparkles size={19} /></div>
            <span className="eyebrow">YOUR PRIVATE AI WORKSPACE</span>
            <h1>Ideas, meet<br /><em>intelligence.</em></h1>
            <p>A thoughtful space for creating with AI — built to run close to home.</p>
            <div className="local-chip"><span className="status-dot" /> Private by design</div>
          </div>
          <div className="auth-art-foot">LOUF AI <span>·</span> PERSONAL INTELLIGENCE</div>
        </div>
        <section className="auth-panel">
          <form onSubmit={submitAuth} className="auth-form">
            <span className="eyebrow">{resetToken ? 'SECURE PASSWORD RESET' : forgotPassword ? 'ACCOUNT RECOVERY' : registering ? 'GET STARTED' : 'WELCOME BACK'}</span>
            <h2>{resetToken ? 'Choose a new password' : forgotPassword ? 'Reset your password' : registering ? 'Create your account' : 'Sign in to LOUF'}</h2>
            <p className="muted">{resetToken ? 'Choose a new password for your account.' : forgotPassword ? 'We’ll email a secure reset link if the account exists.' : registering ? 'Set up your private workspace.' : 'Your conversations are waiting.'}</p>
            {!resetToken && <><label htmlFor="email">Email address</label>
            <input id="email" type="email" autoComplete="email" required value={email} onChange={(e) => setEmail(e.target.value)} /></>}
            {!forgotPassword && <><label htmlFor="password">Password</label>
            <input id="password" type="password" autoComplete={registering || resetToken ? 'new-password' : 'current-password'} minLength={12} required value={password} onChange={(e) => setPassword(e.target.value)} />
            <small className="field-hint">Use at least 12 characters.</small></>}
            {authError && <div className="inline-error" role="alert">{authError}</div>}
            {authNotice && <div className="inline-notice" role="status">{authNotice}</div>}
            <button className="primary-button auth-submit" disabled={busy}>
              {busy ? <LoaderCircle className="spin" size={17} /> : resetToken ? 'Update password' : forgotPassword ? 'Send reset link' : registering ? 'Create account' : 'Sign in'}
              {!busy && <ArrowUp size={16} />}
            </button>
            {!registering && !forgotPassword && !resetToken && <p className="auth-switch"><button type="button" onClick={() => { setForgotPassword(true); setAuthError(''); setAuthNotice('') }}>Forgot password?</button></p>}
            {!resetToken && <p className="auth-switch">{forgotPassword ? 'Remembered your password?' : registering ? 'Already have an account?' : 'New to LOUF AI?'} <button type="button" onClick={() => { setForgotPassword(false); setRegistering(forgotPassword ? false : !registering); setAuthError(''); setAuthNotice('') }}>{forgotPassword || registering ? 'Sign in' : 'Create account'}</button></p>}
            {!registering && !forgotPassword && !resetToken && <button className="secondary-button guest-button" type="button" disabled={busy} onClick={() => void continueAsGuest()}><Sparkles size={15} /> Continue as guest</button>}
            {!registering && !forgotPassword && !resetToken && <p className="guest-note">Temporary private session. Your chats are deleted when you sign out or the session expires.</p>}
            <div className="privacy-note"><ShieldCheck size={15} /> Your account and sessions are protected.</div>
          </form>
        </section>
      </main>
    )
  }

  const activeConversation = conversations.find((item) => item.id === selectedId)
  const filteredConversations = conversations.filter((item) => item.title.toLowerCase().includes(search.toLowerCase()))
  const navigation: { id: Section; label: string; icon: typeof MessageSquarePlus }[] = [
    { id: 'chat', label: 'Chat', icon: MessageSquarePlus },
    { id: 'images', label: 'Image studio', icon: Image },
    { id: 'videos', label: 'Video studio', icon: Video },
    { id: 'gallery', label: 'Your gallery', icon: GalleryVerticalEnd },
  ]

  return (
    <div className="app-shell">
      <aside className={`sidebar ${mobileOpen ? 'sidebar-open' : ''}`}>
        <div className="side-brand"><div className="brand-mark"><Sparkles size={17} /></div><span>louf<span className="brand-ai">.ai</span></span><button className="icon-button mobile-close" aria-label="Close menu" onClick={() => setMobileOpen(false)}><X size={18} /></button></div>
        <button className="new-chat" onClick={createConversation}><Plus size={17} /> New conversation <span>⌘ K</span></button>
        <div className="side-search"><Search size={15} /><input aria-label="Search conversations" placeholder="Search conversations" value={search} onChange={(e) => setSearch(e.target.value)} /></div>
        <div className="side-label">WORKSPACE</div>
        <nav className="main-nav">
          {navigation.map(({ id, label, icon: Icon }) => (
            <button key={id} className={`nav-item ${section === id ? 'active' : ''}`} onClick={() => { setSection(id); setMobileOpen(false) }}><Icon size={17} /><span>{label}</span>{id === 'images' && !capabilities?.images.available && <span className="nav-dot" />}</button>
          ))}
        </nav>
        <div className="history-heading"><span>RECENTS</span><button className="icon-button" aria-label="Create conversation" onClick={createConversation}><Plus size={15} /></button></div>
        <div className="conversation-list">
          {filteredConversations.length ? filteredConversations.map((item) => (
            <div key={item.id} className={`conversation-row ${selectedId === item.id ? 'selected' : ''}`}>
              {renamingId === item.id ? <form className="conversation-rename-form" onSubmit={(event) => void saveConversationTitle(event, item.id)}><input autoFocus aria-label="Conversation title" value={renameTitle} maxLength={160} onChange={(event) => setRenameTitle(event.target.value)} onKeyDown={(event) => { if (event.key === 'Escape') setRenamingId(null) }} /><button className="icon-button" aria-label="Save conversation title"><Check size={14} /></button><button className="icon-button" type="button" aria-label="Cancel rename" onClick={() => setRenamingId(null)}><X size={14} /></button></form> : <><button className="conversation-link" onClick={() => { setSelectedId(item.id); setSection('chat'); setMobileOpen(false) }}><span className="conversation-title">{item.title}</span></button><button className="icon-button conversation-rename" aria-label={`Rename ${item.title}`} onClick={() => { setRenamingId(item.id); setRenameTitle(item.title) }}><Pencil size={14} /></button><button className="icon-button conversation-delete" aria-label={`Delete ${item.title}`} onClick={() => removeConversation(item.id)}><Trash2 size={14} /></button></>}
            </div>
          )) : <p className="side-empty">{search ? 'No matching conversations' : 'Your chats will appear here'}</p>}
        </div>
        <div className="sidebar-bottom">
          <div className="model-mini"><span className={`status-dot ${models?.connected ? 'online' : 'offline'}`} /><div><strong>{models?.connected ? `${models.models.length} available models` : 'Bionic offline'}</strong><small>{models?.connected ? 'Bionic connected' : 'Check connection'}</small></div><button className="icon-button" onClick={() => setSection('settings')} aria-label="Model settings"><ChevronDown size={16} /></button></div>
          <button className={`nav-item settings-link ${section === 'settings' ? 'active' : ''}`} onClick={() => { setSection('settings'); setMobileOpen(false) }}><Settings size={17} /><span>Settings</span></button>
          <div className="profile-row"><div className="avatar">{user.is_guest ? 'G' : user.email.slice(0, 1).toUpperCase()}</div><div className="profile-details"><strong>{user.is_guest ? 'Guest session' : user.email.split('@')[0]}</strong><small>{user.is_guest ? 'Temporary · chats expire' : user.email}</small></div><button className="icon-button" aria-label={user.is_guest ? 'End guest session' : 'Sign out'} onClick={logout}><LogOut size={16} /></button></div>
        </div>
      </aside>

      <main className="main-panel">
        <header className="topbar">
          <button className="icon-button mobile-menu" aria-label="Open menu" onClick={() => setMobileOpen(true)}><Menu size={19} /></button>
          <div className="breadcrumbs"><span>LOUF AI</span><span className="crumb-sep">/</span><strong>{section === 'chat' ? activeConversation?.title ?? 'New conversation' : navigation.find((item) => item.id === section)?.label ?? 'Settings'}</strong></div>
          <div className="topbar-actions"><span className="private-badge"><ShieldCheck size={14} /> Private workspace</span><button className="icon-button theme-toggle" aria-label="Toggle theme" onClick={() => setDark(!dark)}>{dark ? '☀' : '◐'}</button></div>
        </header>
        {appError && <div className="toast-error" role="alert">{appError}<button aria-label="Dismiss" onClick={() => setAppError('')}><X size={15} /></button></div>}

        {section === 'chat' && (
          <section className="chat-page">
            <div className="message-scroll">
              {!messages.length && !loadingMessages ? (
                <div className="welcome">
                  <div className="welcome-icon"><Sparkles size={21} /></div>
                  <span className="eyebrow">A LITTLE SPACE TO THINK</span>
                  <h1>What’s on your mind<span>?</span></h1>
                  <p>Ask a question, explore an idea, or get help with something you’re working on.</p>
                  <div className="suggestion-grid">
                    {['Help me brainstorm a fresh idea', 'Explain something in simple terms', 'Help me write or refine a draft'].map((suggestion) => <button key={suggestion} onClick={() => { setPrompt(suggestion); promptRef.current?.focus() }}>{suggestion}<ArrowUp size={14} /></button>)}
                  </div>
                  {!models?.connected && <div className="connect-callout"><CircleHelp size={17} /><span><strong>Connect Bionic to begin.</strong> Configure your Bionic-compatible API endpoint on the backend.</span><button onClick={() => setSection('settings')}>Setup guide</button></div>}
                </div>
              ) : (
                <div className="messages">
                  {loadingMessages && <div className="loading-line"><LoaderCircle className="spin" size={16} /> Loading conversation…</div>}
                  {messages.map((message) => (
                    <article className={`message message-${message.role}`} key={message.id}>
                      <div className="message-avatar">{message.role === 'assistant' ? <Sparkles size={15} /> : user.email.slice(0, 1).toUpperCase()}</div>
                      <div className="message-content">
                        <div className="message-byline">{message.role === 'assistant' ? 'LOUF' : 'YOU'}{message.model && <span>{message.model}</span>}</div>
                        <div className="markdown-body"><ReactMarkdown remarkPlugins={[remarkGfm]}>{message.content || (sending ? ' ' : '')}</ReactMarkdown>{!message.content && sending && <span className="typing-dots"><i /><i /><i /></span>}</div>
                        {!!message.content && <div className="message-tools"><button onClick={() => copyMessage(message)}>{copiedId === message.id ? <Check size={14} /> : <Copy size={14} />}{copiedId === message.id ? 'Copied' : 'Copy'}</button>{message.role === 'user' && <button onClick={() => { setPrompt(message.content); promptRef.current?.focus() }}>Edit prompt</button>}{message.role === 'assistant' && <button onClick={() => { const last = [...messages].reverse().find((item) => item.role === 'user'); if (last) void sendMessage(undefined, last.content) }}>Regenerate</button>}</div>}
                      </div>
                    </article>
                  ))}
                  <div ref={endRef} />
                </div>
              )}
            </div>
            <form className="composer-wrap" onSubmit={(event) => void sendMessage(event)}>
              <div className="composer">
                <textarea ref={promptRef} rows={1} placeholder={models?.connected ? 'Message LOUF AI…' : 'Connect Bionic to start a conversation'} value={prompt} onChange={(event) => setPrompt(event.target.value)} onKeyDown={(event) => { if (event.key === 'Enter' && !event.shiftKey) { event.preventDefault(); void sendMessage() } }} aria-label="Message" />
                <div className="composer-bottom"><div className="composer-model"><span className={`status-dot ${models?.connected ? 'online' : 'offline'}`} /><select aria-label="Select model" value={selectedModel} onChange={(event) => setSelectedModel(event.target.value)} disabled={!models?.models.length}><option value="">{models?.models.length ? 'Choose a model' : 'No models available'}</option>{models?.models.map((model) => <option key={model.name} value={model.name}>{model.name}</option>)}</select><ChevronDown size={13} /></div><div className="composer-actions"><span>Bionic API</span>{sending ? <button type="button" className="cancel-button" aria-label="Cancel generation" onClick={() => activeRequest.current?.abort()}><X size={16} /> Stop</button> : <button className="send-button" aria-label="Send message" disabled={!prompt.trim()}><ArrowUp size={18} /></button>}</div></div>
              </div>
              <p className="composer-note">AI can make mistakes. Your prompts are sent to the Bionic endpoint configured by your workspace.</p>
            </form>
          </section>
        )}

        {(section === 'images' || section === 'videos' || section === 'gallery') && (
          <section className="feature-page">
            <div className="feature-heading"><div className="welcome-icon">{section === 'images' ? <Image size={20} /> : section === 'videos' ? <Video size={20} /> : <GalleryVerticalEnd size={20} />}</div><span className="eyebrow">CREATIVE WORKSPACE</span><h1>{section === 'images' ? 'Image studio' : section === 'videos' ? 'Video studio' : 'Your gallery'}</h1><p>{section === 'gallery' ? 'Your generated images and videos are saved privately in this workspace.' : `Create with a local ${section === 'images' ? 'image' : 'video'} workflow in ComfyUI.`}</p></div>
            {section !== 'gallery' && (
              <form className="media-prompt-card" onSubmit={(event) => void generateMedia(event, section === 'images' ? 'image' : 'video')}>
                <label htmlFor={`${section}-prompt`}>{section === 'images' ? 'Describe the image you want to create' : 'Describe the video you want to create'}</label>
                <textarea
                  id={`${section}-prompt`}
                  rows={5}
                  maxLength={2000}
                  placeholder={section === 'images'
                    ? 'A quiet cabin beside a mountain lake at sunrise, soft watercolor style…'
                    : 'A slow cinematic shot gliding over a forest at sunrise, mist moving through the trees…'}
                  value={section === 'images' ? imagePrompt : videoPrompt}
                  onChange={(event) => section === 'images'
                    ? setImagePrompt(event.target.value)
                    : setVideoPrompt(event.target.value)}
                />
                <div className="media-prompt-footer">
                  <span>{(section === 'images' ? imagePrompt : videoPrompt).length}/2000</span>
                  <button className="primary-button media-generate-button" type="submit" disabled={
                    !(section === 'images' ? capabilities?.images.available : capabilities?.videos.available)
                    || !(section === 'images' ? imagePrompt : videoPrompt).trim()
                  }>
                    <Sparkles size={15} /> Generate {section === 'images' ? 'image' : 'video'}
                  </button>
                </div>
              </form>
            )}
            {section !== 'gallery' && !(section === 'images' ? capabilities?.images.available : capabilities?.videos.available) && (
              <div className="unavailable-card"><div className="unavailable-icon"><Activity size={20} /></div><div><span className="status-pill"><span className="status-dot offline" /> NOT CONFIGURED</span><h2>{section === 'images' ? 'Image workflow not configured' : 'Video workflow not configured'}</h2><p>{section === 'images' ? capabilities?.images.message : capabilities?.videos.message}</p><button className="secondary-button" onClick={() => setSection('settings')}><Settings size={15} /> Review provider settings</button></div></div>
            )}
            {visibleMediaJobs.length ? (
              <div className="media-grid">
                {visibleMediaJobs.map((job) => (
                  <article className="media-result-card" key={job.id}>
                    {job.status === 'completed' && job.file_url ? (
                      job.media_type === 'image'
                        ? <img src={job.file_url} alt={job.prompt} loading="lazy" />
                        : <video src={job.file_url} controls preload="metadata" />
                    ) : (
                      <div className={`media-result-placeholder ${job.status === 'failed' ? 'media-failed' : ''}`}>
                        {job.status === 'failed' ? <Activity size={20} /> : <LoaderCircle className="spin" size={20} />}
                        <strong>{job.status === 'failed' ? 'Generation failed' : `Generation ${job.status}`}</strong>
                        {job.error && <span role="alert">{job.error}</span>}
                      </div>
                    )}
                    <div className="media-result-details">
                      <p>{job.prompt}</p>
                      <span>{job.media_type} · {new Date(job.created_at).toLocaleString()}</span>
                      <button className="icon-button" aria-label="Delete generated media" onClick={() => void deleteMediaJob(job)}><Trash2 size={15} /></button>
                    </div>
                  </article>
                ))}
              </div>
            ) : (
              <div className="media-empty">
                <GalleryVerticalEnd size={21} />
                <strong>{section === 'gallery' ? 'Your gallery is empty' : `No ${section === 'images' ? 'images' : 'videos'} yet`}</strong>
                <span>Generated files will appear here when ComfyUI finishes a workflow.</span>
              </div>
            )}
            <div className="honest-note"><ShieldCheck size={16} /><span>Generation runs through your configured ComfyUI server. Media files are private to your account.</span></div>
          </section>
        )}

        {section === 'settings' && (
          <section className="settings-page">
            <div className="settings-intro"><span className="eyebrow">PREFERENCES</span><h1>Settings</h1><p>Manage your Bionic connection and personal workspace.</p></div>
            <div className="settings-section"><div className="settings-title"><div><h2>Bionic chat provider</h2><p>Chat requests use the Bionic-compatible endpoint configured on the backend.</p></div><span className={`status-pill ${models?.connected ? 'pill-good' : ''}`}><span className={`status-dot ${models?.connected ? 'online' : 'offline'}`} />{models?.connected ? 'CONNECTED' : 'OFFLINE'}</span></div><div className="settings-card"><div className="settings-card-main"><div className="settings-icon"><Activity size={18} /></div><div><strong>{models?.connected ? 'Bionic is reachable' : 'Bionic is not connected'}</strong><p>{models?.connected ? `${models.models.length} model${models.models.length === 1 ? '' : 's'} available from the configured endpoint.` : models?.message ?? 'Configure BIONIC_API_BASE_URL on the backend, then check the connection.'}</p></div></div><button className="secondary-button" onClick={() => void refreshModels().catch((error: Error) => setAppError(error.message))}><Activity size={14} /> Check connection</button></div>{models?.connected && !models.models.length && <div className="setup-tip"><strong>No models available</strong><p>Check that your Bionic deployment has at least one model enabled and that its OpenAI-compatible <code>/models</code> endpoint is enabled.</p></div>}{models?.connected && models.models.length > 0 && <div className="model-list">{models.models.map((model) => <div key={model.name}><span className="status-dot online" /><strong>{model.name}</strong><small>Available from Bionic</small></div>)}</div>}<div className="setup-tip"><strong>Configure Bionic securely</strong><p>Set <code>BIONIC_API_BASE_URL</code> and, if required, <code>BIONIC_API_KEY</code> in <code>python-backend\\.env</code>, then restart the backend. Credentials are never sent to the browser. The endpoint must support OpenAI-compatible <code>/models</code> and streaming <code>/chat/completions</code>.</p></div></div>
            <div className="settings-section"><div className="settings-title"><div><h2>Image &amp; video providers</h2><p>Run a local ComfyUI server and configure API-format workflows in the backend environment.</p></div></div>{(['images', 'videos'] as const).map((kind) => { const capability = capabilities?.[kind]; return <div className="settings-card" key={kind}><div className="settings-card-main"><div className="settings-icon">{kind === 'images' ? <Image size={18} /> : <Video size={18} />}</div><div><strong>{kind === 'images' ? 'Image' : 'Video'} generation · {capability?.available ? 'Configured' : 'Not configured'}</strong><p>{capability?.message ?? 'Provider status is not available.'}</p></div></div><span className={`status-pill ${capability?.available ? 'pill-good' : ''}`}><span className={`status-dot ${capability?.available ? 'online' : 'offline'}`} />{capability?.available ? 'CONFIGURED' : 'SETUP NEEDED'}</span></div> })}<div className="setup-tip"><strong>ComfyUI setup</strong><p>Set <code>COMFYUI_API_BASE_URL</code>, each workflow JSON path, prompt node ID, and prompt input name in <code>python-backend\\.env</code>. Export workflows in ComfyUI API format. See the README for details; provider credentials stay on the backend.</p></div></div>
            <div className="settings-section account-section"><div className="settings-title"><div><h2>Account</h2><p>{user.is_guest ? 'Using a temporary guest session' : `Signed in as ${user.email}`}</p></div></div><div className="settings-card"><div className="settings-card-main"><div className="settings-icon"><ShieldCheck size={18} /></div><div><strong>{user.is_guest ? 'Temporary private workspace' : 'Private workspace'}</strong><p>{user.is_guest ? 'Chats are isolated to this guest session and deleted when you sign out or it expires.' : 'Your conversation history is private to your account. Session cookie is HTTP-only.'}</p></div></div>{user.is_guest ? <button className="secondary-button danger-button" onClick={() => void logout()}><LogOut size={14} /> End guest session</button> : <button className="secondary-button danger-button" onClick={() => { if (window.confirm('Permanently delete your account and all conversations? This cannot be undone.')) void api('/users/me', { method: 'DELETE' }).then(() => setUser(null)).catch((error: Error) => setAppError(error.message)) }}><Trash2 size={14} /> Delete account</button>}</div><div className="settings-card"><div className="settings-card-main"><div className="settings-icon"><MoreHorizontal size={18} /></div><div><strong>Theme</strong><p>Choose a comfortable appearance for your workspace.</p></div></div><button className="secondary-button" onClick={() => setDark(!dark)}>{dark ? 'Use light theme' : 'Use dark theme'}</button></div></div>
            <div className="settings-footer">Password recovery links expire after 30 minutes. Configure SMTP_HOST and SMTP_FROM_EMAIL on the server to deliver them.</div>
          </section>
        )}
      </main>
    </div>
  )
}

export default App
