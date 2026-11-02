"""Small SDL2/SDL_ttf binding using libraries already on the TV."""
import ctypes as C
import os
from pathlib import Path


class Rect(C.Structure):
    _fields_ = [('x', C.c_int), ('y', C.c_int), ('w', C.c_int), ('h', C.c_int)]


class Color(C.Structure):
    _fields_ = [('r', C.c_uint8), ('g', C.c_uint8), ('b', C.c_uint8), ('a', C.c_uint8)]


class Canvas:
    WIDTH, HEIGHT = 1280, 720

    def __init__(self, app_id):
        os.environ.update(APPID=app_id, XDG_RUNTIME_DIR='/tmp/xdg',
                          SDL_VIDEODRIVER='wayland', SDL_VIDEO_WAYLAND_WMCLASS=app_id,
                          SDL_VIDEO_X11_WMCLASS=app_id)
        self.sdl = C.CDLL('libSDL2-2.0.so.0')
        self.ttf = C.CDLL('libSDL2_ttf-2.0.so.0')
        self.window = self.renderer = None
        self.fonts = {}
        self.video = self.text_ready = False
        try:
            self.error = self.bind(self.sdl, 'SDL_GetError', C.c_char_p, [])
            if self.bind(self.sdl, 'SDL_Init', C.c_int, [C.c_uint])(0x20) != 0:
                raise RuntimeError(self.error())
            self.video = True
            self.window = self.bind(self.sdl, 'SDL_CreateWindow', C.c_void_p,
                                    [C.c_char_p, C.c_int, C.c_int, C.c_int, C.c_int, C.c_uint])(
                b'Magic Sirimote', 0, 0, self.WIDTH, self.HEIGHT, 4)
            if not self.window:
                raise RuntimeError(self.error())
            self.renderer = self.bind(self.sdl, 'SDL_CreateRenderer', C.c_void_p,
                                      [C.c_void_p, C.c_int, C.c_uint])(self.window, -1, 2)
            if not self.renderer:
                raise RuntimeError(self.error())
            self.bind(self.sdl, 'SDL_RenderSetLogicalSize', C.c_int,
                      [C.c_void_p, C.c_int, C.c_int])(self.renderer, self.WIDTH, self.HEIGHT)
            if self.bind(self.ttf, 'TTF_Init', C.c_int, [])() != 0:
                raise RuntimeError(self.error())
            self.text_ready = True
            # Font files are supplied by the TV, never copied into the IPK.
            candidates = ('/usr/share/fonts/LG_Smart_UI-Regular.ttf',
                          '/usr/share/fonts/DroidSans.ttf',
                          '/usr/share/fonts/ttf/LiberationSans-Regular.ttf')
            self.font_path = next((p for p in candidates if Path(p).is_file()), None)
            if not self.font_path:
                raise RuntimeError('No supported TV font is available.')
            self.set_color = self.bind(self.sdl, 'SDL_SetRenderDrawColor', C.c_int,
                                       [C.c_void_p, C.c_uint8, C.c_uint8, C.c_uint8, C.c_uint8])
            self.fill = self.bind(self.sdl, 'SDL_RenderFillRect', C.c_int, [C.c_void_p, C.POINTER(Rect)])
            self.copy = self.bind(self.sdl, 'SDL_RenderCopy', C.c_int,
                                  [C.c_void_p, C.c_void_p, C.c_void_p, C.POINTER(Rect)])
            self.poll = self.bind(self.sdl, 'SDL_PollEvent', C.c_int, [C.c_void_p])
            self.present_frame = self.bind(self.sdl, 'SDL_RenderPresent', None, [C.c_void_p])
            self.clear_frame = self.bind(self.sdl, 'SDL_RenderClear', C.c_int, [C.c_void_p])
            self.start_text = self.bind(self.sdl, 'SDL_StartTextInput', None, [])
            self.stop_text = self.bind(self.sdl, 'SDL_StopTextInput', None, [])
        except BaseException:
            self.close()
            raise

    @staticmethod
    def bind(lib, name, returns, arguments):
        function = getattr(lib, name)
        function.restype, function.argtypes = returns, arguments
        return function

    def rectangle(self, bounds, color):
        self.set_color(self.renderer, *color, 255)
        self.fill(self.renderer, C.byref(Rect(*bounds)))

    def clear(self):
        self.set_color(self.renderer, 17, 24, 34, 255)
        self.clear_frame(self.renderer)

    def text(self, value, x, y, size=24, color=(226, 234, 243), max_width=1120):
        if size not in self.fonts:
            font = self.bind(self.ttf, 'TTF_OpenFont', C.c_void_p, [C.c_char_p, C.c_int])(self.font_path.encode(), size)
            if not font:
                raise RuntimeError(self.error())
            self.fonts[size] = font
        render = self.bind(self.ttf, 'TTF_RenderUTF8_Blended', C.c_void_p,
                           [C.c_void_p, C.c_char_p, Color])
        surface = render(self.fonts[size], value.encode(), Color(*color, 255))
        if not surface:
            raise RuntimeError(self.error())
        texture = None
        try:
            texture = self.bind(self.sdl, 'SDL_CreateTextureFromSurface', C.c_void_p,
                                [C.c_void_p, C.c_void_p])(self.renderer, surface)
            if not texture:
                raise RuntimeError(self.error())
            width, height = C.c_int(), C.c_int()
            self.bind(self.sdl, 'SDL_QueryTexture', C.c_int,
                      [C.c_void_p, C.c_void_p, C.c_void_p, C.POINTER(C.c_int), C.POINTER(C.c_int)])(
                texture, None, None, C.byref(width), C.byref(height))
            scale = min(1, max_width / max(1, width.value))
            self.copy(self.renderer, texture, None,
                      C.byref(Rect(x, y, int(width.value * scale), int(height.value * scale))))
        finally:
            if texture:
                self.bind(self.sdl, 'SDL_DestroyTexture', None, [C.c_void_p])(texture)
            self.bind(self.sdl, 'SDL_FreeSurface', None, [C.c_void_p])(surface)

    def events(self):
        event = C.create_string_buffer(64)
        while self.poll(event):
            raw = event.raw
            kind = int.from_bytes(raw[:4], 'little')
            if kind == 0x100 or (kind == 0x200 and raw[12] == 14):
                yield ('close', None)
            elif kind == 0x300:  # SDL_KeyboardEvent: keysym.sym is at byte 20.
                yield ('key', int.from_bytes(raw[20:24], 'little', signed=True))
            elif kind == 0x303:
                yield ('text', raw[12:44].split(b'\0', 1)[0].decode('utf-8', 'replace'))
            elif kind == 0x402 and raw[16] == 1:  # Left mouse button release.
                yield ('click', (int.from_bytes(raw[20:24], 'little', signed=True),
                                 int.from_bytes(raw[24:28], 'little', signed=True)))

    def present(self):
        self.present_frame(self.renderer)

    def close(self):
        for font in self.fonts.values():
            self.bind(self.ttf, 'TTF_CloseFont', None, [C.c_void_p])(font)
        self.fonts.clear()
        if self.text_ready:
            self.bind(self.ttf, 'TTF_Quit', None, [])()
            self.text_ready = False
        if self.renderer:
            self.bind(self.sdl, 'SDL_DestroyRenderer', None, [C.c_void_p])(self.renderer)
            self.renderer = None
        if self.window:
            self.bind(self.sdl, 'SDL_DestroyWindow', None, [C.c_void_p])(self.window)
            self.window = None
        if self.video:
            self.bind(self.sdl, 'SDL_Quit', None, [])()
            self.video = False
