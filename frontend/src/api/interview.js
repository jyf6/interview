const API_BASE_URL = import.meta.env.VITE_API_BASE_URL ?? 'http://127.0.0.1:8000/api/v1'

async function request(path, options = {}) {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    headers: {
      'Content-Type': 'application/json',
      ...(options.headers ?? {}),
    },
    ...options,
  })

  if (!response.ok) {
    const message = await response.text()
    throw new Error(message || `Request failed: ${response.status}`)
  }

  return response.json()
}

export function startDialog(sessionId = null, userId = '') {
  return request('/interview/dialog/start', {
    method: 'POST',
    body: JSON.stringify({ session_id: sessionId, user_id: userId }),
  })
}

export function sendDialogAction(payload) {
  return request('/interview/dialog/actions', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export function sendDialogText(payload) {
  return request('/interview/dialog/text', {
    method: 'POST',
    body: JSON.stringify(payload),
  })
}

export function sendSessionCommand(sessionId, payload) {
  return request(`/interview/sessions/${sessionId}/commands`, {
    method: 'POST',
    body: JSON.stringify({ session_id: sessionId, ...payload }),
  })
}

export function createBiography(intervieweeId = null) {
  return request('/biographies', {
    method: 'POST',
    body: JSON.stringify({ interviewee_id: intervieweeId }),
  })
}

export function startHighlightSession(biographyId, sessionId = null) {
  return request(`/biographies/${biographyId}/highlight-sessions`, {
    method: 'POST',
    body: JSON.stringify({ session_id: sessionId }),
  })
}

export function sendHighlightMessage(biographyId, sessionId, content) {
  return request(`/biographies/${biographyId}/highlight-sessions/${sessionId}/messages`, {
    method: 'POST',
    body: JSON.stringify({ session_id: sessionId, content }),
  })
}

export function updateOutline(outlineId, chapters) {
  return request(`/outlines/${outlineId}`, {
    method: 'PUT',
    body: JSON.stringify({ chapters }),
  })
}

export function publishOutline(outlineId) {
  return request(`/outlines/${outlineId}/publish`, { method: 'POST' })
}

export function createOutlineSession(biographyId, outlineId, sessionId = null) {
  return request('/interview/sessions', {
    method: 'POST',
    body: JSON.stringify({ biography_id: biographyId, outline_id: outlineId, session_id: sessionId }),
  })
}

export function getInterviewState(sessionId) {
  return request(`/interview/state/${sessionId}`)
}

export function getUserInfo(userId) {
  return request(`/interview/users/${userId}/userinfo`)
}

export function saveUserInfo(userId, payload) {
  return request(`/interview/users/${userId}/userinfo`, {
    method: 'PUT',
    body: JSON.stringify(payload),
  })
}

/**
 * 流式获取开场白，每收到一个 token 就调用 onToken(token)。
 * 结束后调用 onComplete(fullText)。
 */
export async function streamOpening(sessionId, userId, { onToken, onComplete }) {
  const params = new URLSearchParams()
  if (userId) params.set('user_id', userId)
  const url = `${API_BASE_URL}/interview/dialog/opening/${sessionId}?${params}`

  const response = await fetch(url, {
    headers: { Accept: 'text/event-stream' },
  })
  if (!response.ok) {
    throw new Error(`Opening stream failed: ${response.status}`)
  }

  const reader = response.body.getReader()
  const decoder = new TextDecoder()
  let fullText = ''
  let buffer = ''

  while (true) {
    const { done, value } = await reader.read()
    if (done) break

    buffer += decoder.decode(value, { stream: true })
    const lines = buffer.split('\n')
    buffer = lines.pop() ?? ''

    for (const line of lines) {
      if (!line.startsWith('data: ')) continue
      const data = line.slice(6).trim()
      if (data === '[DONE]') {
        onComplete?.(fullText)
        return fullText
      }
      try {
        const parsed = JSON.parse(data)
        const token = parsed.token ?? ''
        if (token) {
          fullText += token
          onToken?.(token, fullText)
        }
      } catch {
        // skip malformed SSE data
      }
    }
  }

  onComplete?.(fullText)
  return fullText
}
