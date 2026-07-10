## Plan for Optimizing the TUI with Modern Textual Design

Based on my analysis of the current project and the provided Textual-based TUI design, I will optimize the TUI implementation with the following approach:

### Current State Analysis:
- The project currently uses **Rich** for terminal UI rendering (src/coding_agent/ui/terminal.py and src/coding_agent/ui/input.py)
- The CLI entry point is in src/coding_agent/cli.py using Typer
- Textual (textual>=0.82.0) is already listed as a dependency in pyproject.toml

### Target Design Features (from the provided text):
1. Dark theme with accent colors
2. User/Assistant message bubbles with distinct styling
3. Auto-scrolling chat view
4. Keyboard shortcuts (Enter to send)
5. Modern input area with submit button
6. Status bar for showing AI thinking state

### Implementation Plan:

#### Phase 1: Create Textual-based TUI Application
Create a new file src/coding_agent/ui/textual_app.py that implements the modern TUI with:
- Main app class extending textual.app.App
- CSS styling for dark theme, message bubbles, input area, and status bar
- Chat view with scrollable container for messages
- Input area with text field and send button
- Message rendering for user and assistant messages

#### Phase 2: Modify CLI Entry Point
Update src/coding_agent/cli.py to support launching the Textual TUI application as an alternative to the current Rich-based interactive mode.

#### Phase 3: Implement Core TUI Features
1. **Message Bubbles**: User messages aligned right with dark surface background, assistant messages aligned left with primary color background
2. **Auto-scrolling**: Automatically scroll to the bottom when new messages are added
3. **Status Bar**: Show "Ready", "🤔 AI is thinking...", "✅ Ready" states
4. **Keyboard Shortcuts**: Support Enter to send message

### Key Files to Create/Modify:
1. **New file**: src/coding_agent/ui/textual_app.py - Main Textual TUI application
2. **Modify**: src/coding_agent/cli.py - Add support for launching the Textual TUI

### Design Choices:
- Keep the existing Rich-based UI as a fallback/legacy option
- Make the Textual TUI available as an alternative mode
- Maintain compatibility with the existing Agent core and tool system
- Use the CSS styling patterns from the provided reference code for consistent modern appearance