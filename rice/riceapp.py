from __future__ import unicode_literals
import sys
import time
import os

from .session import RSession
from . import interface
from . import api
from . import callbacks
from .modalprompt import ModalPrompt
from .modalhistory import ModalFileHistory

from prompt_toolkit.eventloop import create_event_loop, set_event_loop
from prompt_toolkit.application.current import get_app
from prompt_toolkit.layout.lexers import PygmentsLexer, DynamicLexer
from prompt_toolkit.completion import DynamicCompleter
from pygments.lexers.r import SLexer
from prompt_toolkit.styles import default_style, merge_styles, style_from_pygments
from pygments.styles import get_style_by_name

from prompt_toolkit.formatted_text import ANSI
from prompt_toolkit.enums import EditingMode

from .keybinding import create_keybindings
from .completion import RCompleter, SmartPathCompleter


PROMPT = "\x1b[34mr$>\x1b[0m "
SHELL_PROMPT = "\x1b[31m!%>\x1b[0m "


def create_modal_prompt():

    def process_events(context):
        while True:
            if context.input_is_ready():
                break
            api.process_events()
            time.sleep(1.0 / 30)

    set_event_loop(create_event_loop(inputhook=process_events))

    def get_lexer():
        app = get_app(return_none=False)
        if hasattr(app, "mp"):
            if app.mp.prompt_mode == "r":
                return PygmentsLexer(SLexer)
        return None

    def get_completer():
        app = get_app(return_none=False)
        if hasattr(app, "mp"):
            if app.mp.prompt_mode == "r":
                return RCompleter()
            elif app.mp.prompt_mode == "shell":
                return SmartPathCompleter()
        return None

    history = ModalFileHistory(
        os.path.join(os.path.expanduser("~"), ".rice_history"),
        exclude_modes=["readline"])

    def on_render(app):
        if app.is_aborting and not app.mp.prompt_mode == "readline":
            app.output.write("\n")

    mp = ModalPrompt(
        lexer=DynamicLexer(get_lexer),
        completer=DynamicCompleter(get_completer),
        history=history,
        extra_key_bindings=create_keybindings(),
        on_render=on_render
    )

    # r mode message is set by RiceApplication.app_initialize()
    mp.prompt_mode = "r"

    return mp


class RiceApplication(object):
    initialized = False

    def app_initialize(self, mp):
        if sys.platform.startswith('win'):
            callbacks.ENCODING = interface.encoding()

        if interface.get_option("rice.editing_mode", "emacs") in ["vim", "vi"]:
            mp.app.editing_mode = EditingMode.VI
        else:
            mp.app.editing_mode = EditingMode.EMACS

        color_scheme = interface.get_option("rice.color_scheme", "native")
        self.style = style_from_pygments(get_style_by_name(color_scheme))

        mp.app.auto_indentation = interface.get_option("rice.auto_indentation", 1) == 1
        mp.complete_while_typing = interface.get_option("rice.complete_while_typing", 1) == 1

        prompt = interface.get_option("rice.prompt", None)
        if prompt:
            mp.set_prompt_mode_message("r", ANSI(prompt))
        else:
            sys_prompt = interface.get_option("prompt")
            if sys_prompt == "> ":
                prompt = PROMPT
            else:
                prompt = sys_prompt

        self.default_prompt = prompt
        mp.set_prompt_mode_message("r", ANSI(prompt))
        interface.set_option("prompt", prompt)

        shell_prompt = interface.get_option("rice.shell_prompt", SHELL_PROMPT)
        mp.set_prompt_mode_message("shell", ANSI(shell_prompt))

        # necessary on windows
        interface.set_option("menu.graphics", False)

        # print welcome message
        sys.stdout.write(interface.r_version())

    def run(self):
        mp = create_modal_prompt()
        mp.interrupted = False

        def result_from_prompt(message, add_history=True):
            if not self.initialized:
                self.app_initialize(mp)
                message = self.default_prompt
                self.initialized = True

            if mp.interrupted:
                mp.interrupted = False
            else:
                sys.stdout.write("\n")

            text = None
            while text is None:
                try:
                    if message == self.default_prompt:
                        mp.prompt_mode = "r"
                        text = mp.prompt(style=self.style)
                    else:
                        # invoked by `readline`
                        mp.set_prompt_mode_message("readline", ANSI(message))
                        mp.prompt_mode = "readline"
                        text = mp.prompt()

                except Exception as e:
                    if isinstance(e, EOFError):
                        # todo: confirmation
                        return None
                    else:
                        print(e)
                        return None
                except KeyboardInterrupt:
                    if mp.prompt_mode == "readline":
                        mp.interrupted = True
                        api.interrupts_pending(True)
                        api.check_user_interrupt()

            return text

        rsession = RSession()
        rsession.read_console = callbacks.create_read_console(result_from_prompt)
        rsession.write_console_ex = callbacks.write_console_ex
        rsession.clean_up = callbacks.clean_up
        rsession.show_message = callbacks.show_message

        # to make api work
        api.rsession = rsession

        rsession.run()