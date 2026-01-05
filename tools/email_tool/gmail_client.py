"""
Gmail API Client Wrapper
Handles all Gmail operations with OAuth token management.
"""

import logging
import base64
from email.mime.text import MIMEText
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List, Optional
from googleapiclient.discovery import build
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request
from flask import current_app
from db import get_db_connection, return_db_connection


class GmailClient:
    """
    Gmail API client with automatic token refresh.
    Handles all Gmail operations for the email tool agent.
    """
    
    def __init__(self, user_id: int):
        """
        Initialize Gmail client for a specific user.
        
        Args:
            user_id: User ID to fetch Gmail credentials for
        
        Raises:
            ValueError: If user hasn't connected Gmail
        """
        self.user_id = user_id
        self.credentials = self._load_credentials()
        
        if not self.credentials:
            raise ValueError(f"No Gmail credentials found for user {user_id}")
        
        # Refresh token if expired
        if self.credentials.expired and self.credentials.refresh_token:
            self.credentials.refresh(Request())
            self._save_credentials()
        
        # Build Gmail service
        self.service = build('gmail', 'v1', credentials=self.credentials)
        logging.info(f"GmailClient initialized for user {user_id}")
    
    def _load_credentials(self) -> Optional[Credentials]:
        """Load user's Gmail credentials from database."""
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT access_token, refresh_token, token_expiry FROM user_gmail_tokens WHERE user_id = %s",
                (self.user_id,)
            )
            row = cursor.fetchone()
            
            if not row:
                return None
            
            # Parse token expiry - handle both string and datetime from PostgreSQL
            token_expiry = row['token_expiry']
            if token_expiry:
                if isinstance(token_expiry, str):
                    expiry = datetime.fromisoformat(token_expiry.replace('Z', '+00:00'))
                elif isinstance(token_expiry, datetime):
                    expiry = token_expiry
                else:
                    expiry = None
            else:
                expiry = None
            
            # Create credentials object
            creds = Credentials(
                token=row['access_token'],
                refresh_token=row['refresh_token'],
                token_uri='https://oauth2.googleapis.com/token',
                client_id=current_app.config.get('GOOGLE_GMAIL_CLIENT_ID'),
                client_secret=current_app.config.get('GOOGLE_GMAIL_CLIENT_SECRET'),
                scopes=[
                    'https://www.googleapis.com/auth/gmail.readonly',
                    'https://www.googleapis.com/auth/gmail.send',
                    'https://www.googleapis.com/auth/gmail.modify'
                ]
            )
            
            # Set expiry if available
            if expiry:
                creds.expiry = expiry
            
            return creds
        
        finally:
            return_db_connection(conn)
    
    def _save_credentials(self):
        """Save refreshed credentials back to database."""
        conn = get_db_connection()
        try:
            cursor = conn.cursor()
            cursor.execute(
                """UPDATE user_gmail_tokens SET
                   access_token = %s,
                   token_expiry = %s,
                   updated_at = CURRENT_TIMESTAMP
                   WHERE user_id = %s""",
                (
                    self.credentials.token,
                    self.credentials.expiry.isoformat() if self.credentials.expiry else None,
                    self.user_id
                )
            )
            conn.commit()
            logging.info(f"Refreshed Gmail credentials for user {self.user_id}")
        finally:
            return_db_connection(conn)
    
    async def search_emails(
        self,
        from_addr: str = None,
        to_addr: str = None,
        subject: str = None,
        is_unread: bool = None,
        date_after: str = None,
        date_before: str = None,
        query: str = None,
        max_results: int = 10
    ) -> List[Dict[str, Any]]:
        """
        Search emails matching criteria.
        
        Args:
            from_addr: Sender email address
            to_addr: Recipient email address
            subject: Subject keywords
            is_unread: Filter for unread emails
            date_after: ISO date string (e.g., "2025-12-01")
            date_before: ISO date string
            query: Free-form Gmail search query
            max_results: Maximum results to return
        
        Returns:
            List of email dicts with {id, subject, from, to, date, snippet}
        """
        try:
            # Build Gmail query
            query_parts = []
            
            if from_addr:
                query_parts.append(f"from:{from_addr}")
            if to_addr:
                query_parts.append(f"to:{to_addr}")
            if subject:
                query_parts.append(f"subject:{subject}")
            if is_unread is not None:
                query_parts.append("is:unread" if is_unread else "is:read")
            if date_after:
                query_parts.append(f"after:{date_after}")
            if date_before:
                query_parts.append(f"before:{date_before}")
            if query:
                query_parts.append(query)
            
            gmail_query = " ".join(query_parts) if query_parts else ""
            
            logging.info(f"Searching emails with query: {gmail_query}")
            
            # Search emails
            result = self.service.users().messages().list(
                userId='me',
                q=gmail_query,
                maxResults=max_results
            ).execute()
            
            messages = result.get('messages', [])
            
            if not messages:
                return []
            
            # Fetch metadata for each message
            emails = []
            for msg in messages:
                msg_data = self.service.users().messages().get(
                    userId='me',
                    id=msg['id'],
                    format='metadata',
                    metadataHeaders=['From', 'To', 'Subject', 'Date']
                ).execute()
                
                headers = {h['name']: h['value'] for h in msg_data.get('payload', {}).get('headers', [])}
                
                emails.append({
                    'id': msg_data['id'],
                    'subject': headers.get('Subject', '(No subject)'),
                    'from': headers.get('From', ''),
                    'to': headers.get('To', ''),
                    'date': headers.get('Date', ''),
                    'snippet': msg_data.get('snippet', '')
                })
            
            logging.info(f"Found {len(emails)} emails")
            return emails
        
        except Exception as e:
            logging.error(f"Gmail search_emails failed: {e}", exc_info=True)
            raise Exception(f"Failed to search emails: {str(e)}")
    
    async def read_email(self, email_id: str) -> Dict[str, Any]:
        """
        Read full email content.
        
        Args:
            email_id: Gmail message ID
        
        Returns:
            Dict with {id, subject, from, to, date, body, snippet}
        """
        try:
            logging.info(f"Reading email: {email_id}")
            
            msg = self.service.users().messages().get(
                userId='me',
                id=email_id,
                format='full'
            ).execute()
            
            headers = {h['name']: h['value'] for h in msg.get('payload', {}).get('headers', [])}
            
            # Extract body
            body = self._extract_body(msg['payload'])
            
            return {
                'id': msg['id'],
                'subject': headers.get('Subject', '(No subject)'),
                'from': headers.get('From', ''),
                'to': headers.get('To', ''),
                'date': headers.get('Date', ''),
                'body': body,
                'snippet': msg.get('snippet', '')
            }
        
        except Exception as e:
            logging.error(f"Gmail read_email failed: {e}", exc_info=True)
            raise Exception(f"Failed to read email: {str(e)}")
    
    def _extract_body(self, payload) -> str:
        """Extract email body from payload."""
        if 'parts' in payload:
            for part in payload['parts']:
                if part['mimeType'] == 'text/plain':
                    data = part['body'].get('data', '')
                    if data:
                        return base64.urlsafe_b64decode(data).decode('utf-8')
                elif part['mimeType'] == 'text/html':
                    # Fallback to HTML if no plain text
                    data = part['body'].get('data', '')
                    if data:
                        return base64.urlsafe_b64decode(data).decode('utf-8')
        else:
            # Single part message
            data = payload['body'].get('data', '')
            if data:
                return base64.urlsafe_b64decode(data).decode('utf-8')
        
        return "(No body content)"
    
    async def send_email(self, to: str, subject: str, body: str) -> Dict[str, Any]:
        """
        Send an email.
        
        Args:
            to: Recipient email address
            subject: Email subject
            body: Email body (plain text)
        
        Returns:
            Dict with {id, success: true}
        """
        try:
            logging.info(f"Sending email to: {to}")
            
            message = MIMEText(body)
            message['to'] = to
            message['subject'] = subject
            
            raw_message = base64.urlsafe_b64encode(message.as_bytes()).decode('utf-8')
            
            sent_message = self.service.users().messages().send(
                userId='me',
                body={'raw': raw_message}
            ).execute()
            
            logging.info(f"Email sent successfully: {sent_message['id']}")
            
            return {
                'id': sent_message['id'],
                'success': True
            }
        
        except Exception as e:
            logging.error(f"Gmail send_email failed: {e}", exc_info=True)
            raise Exception(f"Failed to send email: {str(e)}")
    
    async def create_draft(self, to: str, subject: str, body: str) -> Dict[str, Any]:
        """Create an email draft without sending."""
        try:
            message = MIMEText(body)
            message['to'] = to
            message['subject'] = subject
            
            raw_message = base64.urlsafe_b64encode(message.as_bytes()).decode('utf-8')
            
            draft = self.service.users().drafts().create(
                userId='me',
                body={'message': {'raw': raw_message}}
            ).execute()
            
            return {
                'id': draft['id'],
                'success': True
            }
        
        except Exception as e:
            logging.error(f"Gmail create_draft failed: {e}", exc_info=True)
            raise Exception(f"Failed to create draft: {str(e)}")
    
    async def mark_as_read(self, email_id: str) -> Dict[str, Any]:
        """Mark email as read."""
        try:
            self.service.users().messages().modify(
                userId='me',
                id=email_id,
                body={'removeLabelIds': ['UNREAD']}
            ).execute()
            
            return {'success': True}
        
        except Exception as e:
            logging.error(f"Gmail mark_as_read failed: {e}", exc_info=True)
            raise Exception(f"Failed to mark as read: {str(e)}")
    
    async def mark_as_unread(self, email_id: str) -> Dict[str, Any]:
        """Mark email as unread."""
        try:
            self.service.users().messages().modify(
                userId='me',
                id=email_id,
                body={'addLabelIds': ['UNREAD']}
            ).execute()
            
            return {'success': True}
        
        except Exception as e:
            logging.error(f"Gmail mark_as_unread failed: {e}", exc_info=True)
            raise Exception(f"Failed to mark as unread: {str(e)}")
    
    async def list_labels(self) -> List[Dict[str, str]]:
        """List all Gmail labels."""
        try:
            results = self.service.users().labels().list(userId='me').execute()
            labels = results.get('labels', [])
            
            return [
                {'id': label['id'], 'name': label['name'], 'type': label.get('type', 'user')}
                for label in labels
            ]
        
        except Exception as e:
            logging.error(f"Gmail list_labels failed: {e}", exc_info=True)
            raise Exception(f"Failed to list labels: {str(e)}")


# Helper function to check if user has Gmail connected
def user_has_gmail_connected(user_id: int) -> bool:
    """Check if user has connected their Gmail account."""
    conn = get_db_connection()
    try:
        cursor = conn.cursor()
        cursor.execute(
            "SELECT 1 FROM user_gmail_tokens WHERE user_id = %s",
            (user_id,)
        )
        return cursor.fetchone() is not None
    finally:
        return_db_connection(conn)