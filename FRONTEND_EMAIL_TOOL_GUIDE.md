# Email Tool Frontend Integration Guide

**Backend URL:** `https://chatbot-backend-wandering-shadow-534.fly.dev`

---

## Overview

The `email_tool` is a tool call made by the main chat LLM. Frontend intercepts this tool call to render a dedicated UI (similar to `search_web` tool). The tool executes on backend and returns structured data to the main chat LLM, which then continues streaming its response naturally.

**Flow:**
```
User message → Main Chat LLM → tool_call: email_tool → Frontend renders Email Tool UI
                                                      → Backend executes → WebSocket events
                                                      → Tool completes → Result to Main Chat LLM
                                                      → Main Chat LLM continues streaming
```

---

## 1. WebSocket Setup

### Connection Timing
Connect WebSocket when frontend loads or user logs in. Maintain throughout session.

### Join Room (Required)

**Frontend emits after WebSocket connects:**
```json
Event: "email_tool_join_room"
{
  "user_id": 42,
  "session_id": "session_abc123"
}
```

**Backend responds:**
```json
Event: "room_joined"
{
  "room": "email_tool_42_session_abc123"
}
```

---

## 2. Detecting Tool Call

When main chat LLM returns a tool call:
```json
{"tool_call": "email_tool", "query": "Search emails from john"}
```

Frontend detects this and renders the Email Tool UI.

---

## 3. UI Requirements

### Design
- Minimal, clean interface
- Subtle border: darker shade on light theme, lighter shade on dark theme
- Professional, modern aesthetic inspired by claude.ai design philosophy
- No modal popups - all interactions within the tool UI panel

### Layout
- **Top left:** Step counter showing current iteration (e.g., "Step 1", "Step 2")
- **Center:** Reasoning text with smooth typing animation
- **Bottom:** Status message when complete ("Task completed with 3 steps")

### Gmail Authentication UI
When `email_tool_needs_auth` received:
- Display within the tool UI panel (no popup modal)
- Show message and "Connect Gmail" button
- Button opens OAuth in new window/popup

### Email Approval UI
When `email_tool_request_approval` received:
- Display within the tool UI panel (no popup modal)
- Show email preview (to, subject, body)
- Show reasoning
- Approve and Reject buttons inline

### Completion
When `email_tool_completed` received:
- Show "Task completed with {total_iterations} steps"
- Main chat LLM will continue streaming its response

---

## 4. Gmail OAuth Endpoints

### Check Status
```
GET /auth/gmail/status
Headers: Authorization: Bearer <jwt_token>

Response (connected):
{
  "connected": true,
  "email_address": "user@gmail.com",
  "connected_since": "2025-12-07T10:00:00"
}

Response (not connected):
{
  "connected": false
}
```

### Initiate OAuth
```
Open popup/window to:
https://chatbot-backend-wandering-shadow-534.fly.dev/auth/gmail/authorize?session_id={session_id}
```

Popup shows Google OAuth page. After completion:
- Popup shows "✅ Gmail Connected!" 
- Auto-closes after 1.5 seconds
- Backend automatically resumes waiting email tool

### Disconnect
```
POST /auth/gmail/disconnect
Headers: Authorization: Bearer <jwt_token>

Response:
{
  "success": true,
  "message": "Gmail disconnected"
}
```

---

## 5. Simulated Scenarios

---

### SCENARIO A: Gmail Not Connected (Auth Required)

**Setup:** User ID: 42, Session: "sess123", Gmail: NOT connected

---

**Step 1: Tool call detected**

Main Chat LLM returns:
```json
{"tool_call": "email_tool", "query": "Search email from john mathew sent on oct 7 2025"}
```
→ Frontend renders Email Tool UI

---

**Step 2: Backend needs auth**

Backend → Frontend (WebSocket):
```json
Event: "email_tool_needs_auth"
{
  "message": "Please connect your Gmail account to continue"
}
```

→ Frontend shows "Connect Gmail" button within tool UI
→ Backend is WAITING (2 minute timeout)

---

**Step 3: User clicks Connect Gmail**

Frontend opens popup:
```
https://chatbot-backend-wandering-shadow-534.fly.dev/auth/gmail/authorize?session_id=sess123
```

User completes OAuth in popup.

Popup shows:
```
✅ Gmail Connected!
Connected as: user@gmail.com
This window will close automatically...
```

Popup auto-closes.

→ Backend automatically resumes (no frontend action needed)

---

**Step 4: Backend continues**

Backend → Frontend:
```json
Event: "email_tool_progress"
{
  "iteration": 1,
  "reasoning": "Analyzing request to find email from John Mathew sent on October 7, 2025."
}
```

→ Frontend shows: "Step 1" + typing animation with reasoning text

---

**Step 5: Backend searches**

Backend → Frontend:
```json
Event: "email_tool_progress"
{
  "iteration": 2,
  "reasoning": "Searching emails with query: from:john mathew after:2025-10-06 before:2025-10-08"
}
```

→ Frontend shows: "Step 2" + typing animation

---

**Step 6: Task complete**

Backend → Frontend:
```json
Event: "email_tool_completed"
{
  "result": {
    "success": true,
    "summary": "Found 1 email from John Mathew dated October 7, 2025. Subject: 'Project Update'.",
    "total_iterations": 3,
    "iterations": [
      {
        "iteration": 1,
        "reasoning": "Analyzing request...",
        "function": null,
        "parameters": null,
        "result": null
      },
      {
        "iteration": 2,
        "reasoning": "Searching emails...",
        "function": "search_emails",
        "parameters": {"query": "from:john mathew after:2025-10-06 before:2025-10-08"},
        "result": {"success": true, "result": [...]}
      }
    ],
    "final_reasoning": "Found 1 email from John Mathew dated October 7, 2025."
  }
}
```

→ Frontend shows: "Task completed with 3 steps"
→ Main chat LLM continues streaming response with email results

---

---

### SCENARIO B: Gmail Connected (Simple Search)

**Setup:** User ID: 42, Session: "sess123", Gmail: CONNECTED

---

**Step 1: Tool call detected**

```json
{"tool_call": "email_tool", "query": "Show my unread emails"}
```
→ Frontend renders Email Tool UI

---

**Step 2: Backend starts immediately (no auth needed)**

Backend → Frontend:
```json
Event: "email_tool_progress"
{
  "iteration": 1,
  "reasoning": "User wants to see unread emails. I will search for unread messages."
}
```

→ Frontend: "Step 1" + typing animation

---

**Step 3: Backend searches**

Backend → Frontend:
```json
Event: "email_tool_progress"
{
  "iteration": 2,
  "reasoning": "Searching for unread emails using query: is:unread"
}
```

→ Frontend: "Step 2" + typing animation

---

**Step 4: Task complete**

Backend → Frontend:
```json
Event: "email_tool_completed"
{
  "result": {
    "success": true,
    "summary": "You have 3 unread emails.",
    "total_iterations": 3,
    "iterations": [...],
    "final_reasoning": "Found 3 unread emails."
  }
}
```

→ Frontend: "Task completed with 3 steps"
→ Main chat continues with email summary

---

---

### SCENARIO C: Send Email (Approval Required)

**Setup:** User ID: 42, Session: "sess123", Gmail: CONNECTED

---

**Step 1: Tool call detected**

```json
{"tool_call": "email_tool", "query": "Send email to john@example.com thanking him"}
```
→ Frontend renders Email Tool UI

---

**Step 2: Backend analyzes**

Backend → Frontend:
```json
Event: "email_tool_progress"
{
  "iteration": 1,
  "reasoning": "User wants to send a thank you email. I will compose and send it."
}
```

→ Frontend: "Step 1" + typing animation

---

**Step 3: Backend composes**

Backend → Frontend:
```json
Event: "email_tool_progress"
{
  "iteration": 2,
  "reasoning": "Composing thank you email with appropriate subject and body."
}
```

→ Frontend: "Step 2" + typing animation

---

**Step 4: Backend requests approval**

Backend → Frontend:
```json
Event: "email_tool_request_approval"
{
  "operation": "send_email",
  "parameters": {
    "to": ["john@example.com"],
    "subject": "Thank You!",
    "body": "Hi John,\n\nThank you for your help on the project.\n\nBest regards",
    "cc": [],
    "bcc": []
  },
  "reasoning": "User wants to send a thank you email. I've composed a professional message."
}
```

→ Backend WAITING (60 second timeout)
→ Frontend shows email preview within tool UI with Approve/Reject buttons (no modal)

---

**Step 5: User clicks Approve**

Frontend → Backend:
```json
Event: "email_tool_user_approved"
{
  "user_id": 42,
  "session_id": "sess123",
  "approved": true
}
```

Backend → Frontend:
```json
Event: "approval_received"
{
  "approved": true
}
```

---

**Step 6: Backend sends email**

Backend → Frontend:
```json
Event: "email_tool_progress"
{
  "iteration": 3,
  "reasoning": "Email sent successfully to john@example.com"
}
```

→ Frontend: "Step 3" + typing animation

---

**Step 7: Task complete**

Backend → Frontend:
```json
Event: "email_tool_completed"
{
  "result": {
    "success": true,
    "summary": "Successfully sent email to john@example.com",
    "total_iterations": 4,
    "iterations": [...],
    "final_reasoning": "Email sent successfully."
  }
}
```

→ Frontend: "Task completed with 4 steps"
→ Main chat continues confirming email sent

---

---

### SCENARIO D: User Rejects Email

**Step 4:** (Same approval request as Scenario C)

**Step 5: User clicks Reject**

Frontend → Backend:
```json
Event: "email_tool_user_approved"
{
  "user_id": 42,
  "session_id": "sess123",
  "approved": false
}
```

---

**Step 6: Task cancelled**

Backend → Frontend:
```json
Event: "email_tool_completed"
{
  "result": {
    "success": false,
    "message": "User rejected email sending",
    "cancelled": true
  }
}
```

→ Frontend: "Task cancelled"
→ Main chat continues acknowledging cancellation

---

---

### SCENARIO E: Auth Timeout

**Step 2:** `email_tool_needs_auth` received

User does nothing for 2 minutes.

**Step 3: Timeout**

Backend → Frontend:
```json
Event: "email_tool_error"
{
  "error": "Gmail authentication timed out. Please try again."
}
```

→ Frontend shows error within tool UI

---

---

### SCENARIO F: Approval Timeout

**Step 4:** `email_tool_request_approval` received

User does nothing for 60 seconds.

**Step 5: Timeout**

Backend → Frontend:
```json
Event: "email_tool_completed"
{
  "result": {
    "success": false,
    "message": "Approval timed out",
    "cancelled": true
  }
}
```

→ Frontend: "Task cancelled - approval timeout"

---

---

## 6. Event Reference

### Events FROM Backend (Listen)

| Event | When | Key Fields |
|-------|------|------------|
| `room_joined` | After joining room | `room` |
| `email_tool_needs_auth` | Gmail not connected | `message` |
| `email_tool_progress` | Each iteration | `iteration`, `reasoning` |
| `email_tool_request_approval` | Before send_email | `operation`, `parameters`, `reasoning` |
| `email_tool_completed` | Task finished | `result.success`, `result.summary`, `result.total_iterations` |
| `email_tool_error` | Error occurred | `error` |
| `approval_received` | Approval acknowledged | `approved` |

### Events TO Backend (Emit)

| Event | When | Payload |
|-------|------|---------|
| `email_tool_join_room` | After WebSocket connects | `{user_id, session_id}` |
| `email_tool_user_approved` | User approves/rejects | `{user_id, session_id, approved}` |

---

## 7. Timeouts

| Action | Timeout |
|--------|---------|
| Gmail Authentication | 2 minutes |
| Email Send Approval | 60 seconds |

---

## 8. Key Points

1. **Tool output goes to main chat LLM** - The email tool result feeds back to the main chat LLM which then continues its response naturally

2. **Detect tool call like search_web** - When LLM returns `{"tool_call": "email_tool", ...}`, render the Email Tool UI

3. **WebSocket must be connected before tool triggers** - Otherwise events will be missed

4. **No modals** - Gmail auth and approval UI displays within the tool panel

5. **session_id consistency** - Use same session_id for WebSocket room and OAuth

6. **Backend handles auth resume** - After OAuth popup closes, backend automatically resumes the waiting task

---

## 9. Quick Start

1. Connect WebSocket on app load
2. Emit `email_tool_join_room` with user_id and session_id
3. Listen for all `email_tool_*` events
4. When detecting `{"tool_call": "email_tool", ...}`, render Email Tool UI
5. Show step counter and reasoning with typing animation
6. Handle auth prompt within UI (opens popup for OAuth)
7. Handle approval within UI (inline approve/reject)
8. On `email_tool_completed`, show completion message
9. Main chat LLM continues streaming naturally
