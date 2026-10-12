/**
 * PrivateMind Frontend API Client
 * Centralized API client for communicating with the FastAPI backend.
 * Provides request timeouts, JSON parsing, and user-friendly error handling.
 */
(function (global) {
  const API_CONFIG = {
    // Single centralized development setting for backend API URL
    baseUrl: (typeof window !== 'undefined' && window.API_BASE_URL) || 'http://127.0.0.1:8000',
    timeoutMs: 12000,
    userId: 'default_user',
    token: typeof localStorage !== 'undefined' ? localStorage.getItem('privatemind_token') || '' : '',
  };

  /**
   * Generic fetch wrapper with AbortController timeout, credentials: 'include', and robust error formatting
   */
  async function request(endpoint, options = {}) {
    const url = `${API_CONFIG.baseUrl}${endpoint}`;
    const controller = new AbortController();
    const timeoutId = setTimeout(() => controller.abort(), options.timeoutMs || API_CONFIG.timeoutMs);

    const headers = {
      'Content-Type': 'application/json',
      Accept: 'application/json',
      ...(options.headers || {}),
    };

    const token = API_CONFIG.token || (typeof localStorage !== 'undefined' ? localStorage.getItem('privatemind_token') : '');
    if (token && !headers['Authorization']) {
      headers['Authorization'] = `Bearer ${token}`;
    }

    const fetchOptions = {
      ...options,
      credentials: 'include',
      headers,
      signal: controller.signal,
    };

    try {
      const response = await fetch(url, fetchOptions);
      clearTimeout(timeoutId);

      let data = null;
      const contentType = response.headers.get('content-type') || '';
      if (contentType.includes('application/json')) {
        data = await response.json().catch(() => null);
      } else {
        const text = await response.text();
        data = { message: text };
      }

      if (!response.ok) {
        const errorDetail = (data && (data.detail || data.message)) || `Server returned status ${response.status}`;
        const err = new Error(typeof errorDetail === 'object' ? JSON.stringify(errorDetail) : errorDetail);
        err.status = response.status;
        err.data = data;
        throw err;
      }

      return data;
    } catch (err) {
      clearTimeout(timeoutId);
      if (err.name === 'AbortError') {
        const timeoutError = new Error(`Request timed out after ${API_CONFIG.timeoutMs / 1000}s. Check if backend is responsive.`);
        timeoutError.isTimeout = true;
        throw timeoutError;
      }
      if (err.message && (err.message.includes('Failed to fetch') || err.message.includes('NetworkError'))) {
        const connError = new Error(`Cannot connect to PrivateMind backend at ${API_CONFIG.baseUrl}. Ensure the FastAPI server is running.`);
        connError.isNetworkError = true;
        throw connError;
      }
      throw err;
    }
  }

  const api = {
    config: API_CONFIG,

    setBaseUrl(url) {
      API_CONFIG.baseUrl = url.replace(/\/+$/, '');
    },

    setUserId(id) {
      API_CONFIG.userId = id;
    },

    /**
     * Check backend health status
     */
    async checkHealth() {
      try {
        const res = await request('/health', { method: 'GET', timeoutMs: 3000 });
        return { online: true, data: res };
      } catch (err) {
        return { online: false, error: err.message };
      }
    },

    /**
     * List all memories with optional search and category filters
     */
    async getMemories({ search = null, category = null, userId = null, skip = 0, limit = 100 } = {}) {
      const params = new URLSearchParams();
      params.append('user_id', userId || API_CONFIG.userId);
      if (search && search.trim()) params.append('search', search.trim());
      if (category && category !== 'All') params.append('category', category.trim());
      if (skip) params.append('skip', skip);
      if (limit) params.append('limit', limit);

      return request(`/memories?${params.toString()}`, { method: 'GET' });
    },

    /**
     * Retrieve a single memory by ID
     */
    async getMemory(memoryId) {
      return request(`/memories/${memoryId}`, { method: 'GET' });
    },

    /**
     * Create a new persistent memory in SQLite
     */
    async createMemory({ title, content, category = 'General', source = 'manual', userId = null }) {
      return request('/memories', {
        method: 'POST',
        body: JSON.stringify({
          title,
          content,
          category,
          source,
          user_id: userId || API_CONFIG.userId,
        }),
      });
    },

    /**
     * Update an existing memory by ID
     */
    async updateMemory(memoryId, { title, content, category, source }) {
      const payload = {};
      if (title !== undefined) payload.title = title;
      if (content !== undefined) payload.content = content;
      if (category !== undefined) payload.category = category;
      if (source !== undefined) payload.source = source;

      return request(`/memories/${memoryId}`, {
        method: 'PATCH',
        body: JSON.stringify(payload),
      });
    },

    /**
     * Delete a single memory by ID
     */
    async deleteMemory(memoryId) {
      return request(`/memories/${memoryId}`, { method: 'DELETE' });
    },

    /**
     * Bulk delete all memories for a user (Privacy Center)
     */
    async deleteAllMemories(userId = null) {
      const uId = userId || API_CONFIG.userId;
      return request(`/memories?user_id=${encodeURIComponent(uId)}`, { method: 'DELETE' });
    },

    /**
     * Semantic memory search
     */
    async searchMemoriesSemantic({ query, threshold = 0.25, limit = 5, category = null, keyword = null, userId = null }) {
      return request('/memories/search', {
        method: 'POST',
        body: JSON.stringify({
          query,
          threshold,
          limit,
          category,
          keyword,
          user_id: userId || API_CONFIG.userId,
        }),
      });
    },

    /**
     * Extract candidate memories from text
     */
    async extractMemories({ message, reviewBeforeSaving = true, userId = null }) {
      return request('/memories/extract', {
        method: 'POST',
        body: JSON.stringify({
          message,
          review_before_saving: reviewBeforeSaving,
          user_id: userId || API_CONFIG.userId,
        }),
      });
    },

    /**
     * Approve extracted candidate memories
     */
    async approveMemories({ candidates, userId = null }) {
      return request('/memories/approve', {
        method: 'POST',
        body: JSON.stringify({
          candidates,
          user_id: userId || API_CONFIG.userId,
        }),
      });
    },

    /**
     * Reject candidate memories
     */
    async rejectMemories({ candidateIds }) {
      return request('/memories/reject', {
        method: 'POST',
        body: JSON.stringify({
          candidate_ids: candidateIds,
        }),
      });
    },

    /**
     * Send chat message to memory-augmented conversational pipeline
     */
    async sendChat({ message, conversationId = null, userId = null, retrievalThreshold = 0.25, maxMemories = 5 }) {
      return request('/chat', {
        method: 'POST',
        body: JSON.stringify({
          message,
          conversation_id: conversationId,
          user_id: userId || API_CONFIG.userId,
          retrieval_threshold: retrievalThreshold,
          max_memories: maxMemories,
        }),
      });
    },

    /**
     * Get conversation turn history
     */
    async getChatHistory(conversationId) {
      return request(`/chat/${encodeURIComponent(conversationId)}`, { method: 'GET' });
    },

    /**
     * Get projects with optional search and status filtering
     */
    async getProjects({ search = null, status = null, userId = null } = {}) {
      const uId = userId || API_CONFIG.userId;
      const params = new URLSearchParams();
      params.append('user_id', uId);
      if (search && search.trim()) params.append('search', search.trim());
      if (status && status !== 'All' && status !== 'all') params.append('status', status.toLowerCase());
      return request(`/projects?${params.toString()}`, { method: 'GET' });
    },

    /**
     * Create a new project workspace
     */
    async createProject({ title, description = '', status = 'active', priority = 'medium', deadline = null, progress = 0, tags = [], theme = 'blue', userId = null }) {
      return request('/projects', {
        method: 'POST',
        body: JSON.stringify({
          title,
          description,
          status,
          priority,
          deadline,
          progress,
          tags,
          theme,
          user_id: userId || API_CONFIG.userId,
        }),
      });
    },

    /**
     * Get detailed workspace for a specific project (overview, notes, tasks, memories, activities)
     */
    async getProjectDetail(projectId, userId = null) {
      const uId = userId || API_CONFIG.userId;
      return request(`/projects/${encodeURIComponent(projectId)}?user_id=${encodeURIComponent(uId)}`, { method: 'GET' });
    },

    /**
     * Update project fields
     */
    async updateProject(projectId, data, userId = null) {
      const uId = userId || API_CONFIG.userId;
      return request(`/projects/${encodeURIComponent(projectId)}?user_id=${encodeURIComponent(uId)}`, {
        method: 'PATCH',
        body: JSON.stringify(data),
      });
    },

    /**
     * Delete a project workspace without deleting global memories
     */
    async deleteProject(projectId, userId = null) {
      const uId = userId || API_CONFIG.userId;
      return request(`/projects/${encodeURIComponent(projectId)}?user_id=${encodeURIComponent(uId)}`, { method: 'DELETE' });
    },

    /**
     * Add a note to a project
     */
    async addProjectNote(projectId, { title, content }, userId = null) {
      const uId = userId || API_CONFIG.userId;
      return request(`/projects/${encodeURIComponent(projectId)}/notes?user_id=${encodeURIComponent(uId)}`, {
        method: 'POST',
        body: JSON.stringify({ title, content }),
      });
    },

    /**
     * Update an existing project note
     */
    async updateProjectNote(projectId, noteId, { title, content }, userId = null) {
      const uId = userId || API_CONFIG.userId;
      return request(`/projects/${encodeURIComponent(projectId)}/notes/${encodeURIComponent(noteId)}?user_id=${encodeURIComponent(uId)}`, {
        method: 'PUT',
        body: JSON.stringify({ title, content }),
      });
    },

    /**
     * Delete a project note
     */
    async deleteProjectNote(projectId, noteId, userId = null) {
      const uId = userId || API_CONFIG.userId;
      return request(`/projects/${encodeURIComponent(projectId)}/notes/${encodeURIComponent(noteId)}?user_id=${encodeURIComponent(uId)}`, { method: 'DELETE' });
    },

    /**
     * Promote a project note to a permanent SQLite memory
     */
    async convertNoteToMemory(projectId, noteId, userId = null) {
      const uId = userId || API_CONFIG.userId;
      return request(`/projects/${encodeURIComponent(projectId)}/notes/${encodeURIComponent(noteId)}/convert-to-memory?user_id=${encodeURIComponent(uId)}`, { method: 'POST' });
    },

    /**
     * Get memories linked to a specific project
     */
    async getProjectMemories(projectId, userId = null) {
      const uId = userId || API_CONFIG.userId;
      return request(`/projects/${encodeURIComponent(projectId)}/memories?user_id=${encodeURIComponent(uId)}`, { method: 'GET' });
    },

    /**
     * Attach an existing memory to a project
     */
    async attachMemoryToProject(projectId, memoryId, userId = null) {
      const uId = userId || API_CONFIG.userId;
      return request(`/projects/${encodeURIComponent(projectId)}/memories?user_id=${encodeURIComponent(uId)}`, {
        method: 'POST',
        body: JSON.stringify({ memory_id: parseInt(memoryId, 10) }),
      });
    },

    /**
     * Detach a memory from a project
     */
    async detachMemoryFromProject(projectId, memoryId, userId = null) {
      const uId = userId || API_CONFIG.userId;
      return request(`/projects/${encodeURIComponent(projectId)}/memories/${encodeURIComponent(memoryId)}?user_id=${encodeURIComponent(uId)}`, { method: 'DELETE' });
    },

    /**
     * Add a task to a project
     */
    async addProjectTask(projectId, { title, description = '', status = 'todo', priority = 'medium', due_date = null }, userId = null) {
      const uId = userId || API_CONFIG.userId;
      return request(`/projects/${encodeURIComponent(projectId)}/tasks?user_id=${encodeURIComponent(uId)}`, {
        method: 'POST',
        body: JSON.stringify({ title, description, status, priority, due_date }),
      });
    },

    /**
     * Update task status, priority, or content
     */
    async updateProjectTask(projectId, taskId, data, userId = null) {
      const uId = userId || API_CONFIG.userId;
      return request(`/projects/${encodeURIComponent(projectId)}/tasks/${encodeURIComponent(taskId)}?user_id=${encodeURIComponent(uId)}`, {
        method: 'PUT',
        body: JSON.stringify(data),
      });
    },

    /**
     * Delete a project task
     */
    async deleteProjectTask(projectId, taskId, userId = null) {
      const uId = userId || API_CONFIG.userId;
      return request(`/projects/${encodeURIComponent(projectId)}/tasks/${encodeURIComponent(taskId)}?user_id=${encodeURIComponent(uId)}`, { method: 'DELETE' });
    },

    /**
     * Get recent activities across projects
     */
    async getRecentActivities({ limit = 10, userId = null } = {}) {
      const uId = userId || API_CONFIG.userId;
      return request(`/projects/activity/recent?limit=${encodeURIComponent(limit)}&user_id=${encodeURIComponent(uId)}`, { method: 'GET' });
    },

    /**
     * Ask AI a question grounded in this specific project's context, notes, tasks, and memories
     */
    async askAIAboutProject(projectId, { message, conversationId = null, userId = null }) {
      return request(`/projects/${encodeURIComponent(projectId)}/chat`, {
        method: 'POST',
        body: JSON.stringify({
          message,
          conversation_id: conversationId,
          user_id: userId || API_CONFIG.userId,
        }),
      });
    },

    // -----------------------------------------------------------------------
    // Phase 7 Authentication & Privacy Endpoints
    // -----------------------------------------------------------------------
    setToken(token) {
      API_CONFIG.token = token || '';
      if (typeof localStorage !== 'undefined') {
        if (token) {
          localStorage.setItem('privatemind_token', token);
        } else {
          localStorage.removeItem('privatemind_token');
        }
      }
    },

    /**
     * Register a new user account
     */
    async register({ username, password, email = null }) {
      const res = await request('/auth/register', {
        method: 'POST',
        body: JSON.stringify({ username, password, email }),
      });
      if (res && res.access_token) {
        api.setToken(res.access_token);
        if (res.user && res.user.username) {
          api.setUserId(res.user.username);
        }
      }
      return res;
    },

    /**
     * Log in an existing user
     */
    async login({ username, password }) {
      const res = await request('/auth/login', {
        method: 'POST',
        body: JSON.stringify({ username, password }),
      });
      if (res && res.access_token) {
        api.setToken(res.access_token);
        if (res.user && res.user.username) {
          api.setUserId(res.user.username);
        }
      }
      return res;
    },

    /**
     * Log out current session
     */
    async logout() {
      try {
        await request('/auth/logout', { method: 'POST' });
      } finally {
        api.setToken('');
      }
    },

    /**
     * Get profile & privacy settings for authenticated user
     */
    async getMe() {
      return request('/auth/me', { method: 'GET' });
    },

    /**
     * Update privacy preferences
     */
    async updateSettings({ memory_enabled = null, auto_extraction = null, review_before_save = null }) {
      const payload = {};
      if (memory_enabled !== null) payload.memory_enabled = memory_enabled;
      if (auto_extraction !== null) payload.auto_extraction = auto_extraction;
      if (review_before_save !== null) payload.review_before_save = review_before_save;

      return request('/auth/settings', {
        method: 'PATCH',
        body: JSON.stringify(payload),
      });
    },

    /**
     * Export all user data (memories & conversations) in portable JSON format
     */
    async exportData() {
      return request('/auth/export', { method: 'GET' });
    },

    /**
     * Permanently delete user account and all data (memories, vectors, conversations)
     */
    async deleteAccount() {
      const res = await request('/auth/account', { method: 'DELETE' });
      api.setToken('');
      return res;
    },

    /**
     * List user's active conversation sessions
     */
    async listChatSessions() {
      return request('/chat/sessions', { method: 'GET' });
    },

    /**
     * Delete a conversation session
     */
    async deleteConversation(conversationId) {
      return request(`/chat/${encodeURIComponent(conversationId)}`, { method: 'DELETE' });
    },

    /**
     * Delete all chat history
     */
    async deleteAllChatHistory() {
      return request('/chat', { method: 'DELETE' });
    },
  };

  global.PrivateMindAPI = api;
  global.api = api;
})(typeof window !== 'undefined' ? window : this);
