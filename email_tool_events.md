# Email Tool WebSocket Events Documentation

This document outlines the WebSocket events used for communication between the frontend and backend for the Email Tool integration.

## 📡 Client → Server (Events Frontend Sends)

These are the events your frontend must emit to the backend.

| Event Name | Payload Structure | Description |
| :--- | :--- | :--- |
| **`email_tool_join_room`** | ```json{ "user_email": "user@example.com", "session_id": "4" }``` | **Critical:** `session_id` MUST match the one sent in the `/chat` POST request. |
| **`email_tool_user_approved`** | ```json{ "user_id": 43, "session_id": "4", "approved": true }``` | Sent when user clicks "Approve" or "Reject" on an email action (like sending). |
| **`email_tool_auth_completed`** | ```json{ "user_id": 43, "session_id": "4", "success": true }``` | Sent after the user successfully completes the Gmail OAuth popup flow. |

---

## 📥 Server → Client (Events Frontend Receives)

These are the events your frontend needs to listen for.

### 1. Connection & Setup Events

| Event Name | Payload Structure | Description |
| :--- | :--- | :--- |
| **`connected`** | ```json{ "status": "ok" }``` | Sent immediately upon socket connection. |
| **`room_joined`** | ```json{ "room": "email_tool_43_4", "user_id": 43, "session_id": "4" }``` | Confirmation that the client has successfully joined the private room. |
| **`error`** | ```json{ "message": "Error description..." }``` | Sent if joining the room fails (e.g., user not found). |

### 2. Email Tool Execution Events

| Event Name | Payload Structure | Description |
| :--- | :--- | :--- |
| **`email_tool_needs_auth`** | ```json{ "message": "Please connect your Gmail account to continue" }``` | **Trigger:** When the tool runs but no Gmail token is found.<br>**Action:** Frontend should open the Gmail OAuth popup. |
| **`email_tool_progress`** | ```json{ "iteration": 1, "reasoning": "Checking if conversation history is needed..." }``` | **Trigger:** Sent before every step the agent takes.<br>**Action:** Display this as a "thinking" or status update in the UI. |
| **`email_tool_request_approval`** | ```json{ "operation": "send_email", "parameters": { "to": "...", "subject": "...", "body": "..." }, "reasoning": "I have drafted the email..." }``` | **Trigger:** When the agent wants to perform a write action (send email).<br>**Action:** Show a UI with "Approve" / "Reject" buttons. |
| **`email_tool_completed`** | ```json{ "result": { "success": true, "summary": "Found 3 emails...", "total_iterations": 2, "iterations": [...] } }``` | **Trigger:** When the tool finishes successfully.<br>**Action:** Update UI to show final state (optional, usually main chat handles the text response). |
| **`email_tool_error`** | ```json{ "error": "Gmail authentication timed out..." }``` | **Trigger:** If the tool fails or times out.<br>**Action:** Show error message to user. |

### 3. Acknowledgment Events

| Event Name | Payload Structure | Description |
| :--- | :--- | :--- |
| **`approval_received`** | ```json{ "approved": true }``` | Confirmation that the backend received your approval/rejection. |
| **`auth_completed_ack`** | ```json{ "status": "ready" }``` | Confirmation that the backend received the auth completion signal and is resuming execution. |

---

## ⚠️ Critical Implementation Checklist

1.  **Session ID Matching:** Ensure the `session_id` passed to `email_tool_join_room` is **identical** to the `session_id` sent in the `/chat` API request.
2.  **Auth Flow Sequence:**
    *   Listen for `email_tool_needs_auth`.
    *   Open OAuth popup.
    *   On success, emit `email_tool_auth_completed`.
    *   Wait for backend to resume (watch for `email_tool_progress`).
3.  **Type Consistency:** The backend now handles type conversion, but it is best practice to send `user_id` as an integer and `session_id` as a string if possible.
