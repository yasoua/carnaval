import gzip
import os
import xml.dom
from typing import BinaryIO

from barcode.version import version

try:
    import Image
    import ImageDraw
    import ImageFont
except ImportError:
    try:
        from PIL import Image  # lint:ok
        from PIL import ImageDraw
        from PIL import ImageFont
    except ImportError:
        import logging

        log = logging.getLogger("pyBarcode")
        log.info("Pillow not found. Image output disabled")
        Image = ImageDraw = ImageFont = None  # lint:ok


def mm2px(mm, dpi=300):
    return (mm * dpi) / 25.4


def pt2mm(pt):
    return pt * 0.352777778


def _set_attributes(element, **attributes):
    for key, value in attributes.items():
        element.setAttribute(key, value)


def create_svg_object(with_doctype=False):
    imp = xml.dom.getDOMImplementation()
    doctype = imp.createDocumentType(
        "svg",
        "-//W3C//DTD SVG 1.1//EN",
        "http://www.w3.org/Graphics/SVG/1.1/DTD/svg11.dtd",
    )
    document = imp.createDocument(None, "svg", doctype if with_doctype else None)
    _set_attributes(
        document.documentElement, version="1.1", xmlns="http://www.w3.org/2000/svg"
    )
    return document


SIZE = "{0:.3f}mm"
COMMENT = f"Autogenerated with python-barcode {version}"
PATH = os.path.dirname(os.path.abspath(__file__))


class BaseWriter:
    """Baseclass for all writers.

    Initializes the basic writer options. Childclasses can add more
    attributes and can set them directly or using
    `self.set_options(option=value)`.

    :parameters:
        initialize : Function
            Callback for initializing the inheriting writer.
            Is called: `callback_initialize(raw_code)`
        paint_module : Function
            Callback for painting one barcode module.
            Is called: `callback_paint_module(xpos, ypos, width, color)`
        paint_text : Function
            Callback for painting the text under the barcode.
            Is called: `callback_paint_text(xpos, ypos)` using `self.text`
            as text.
        finish : Function
            Callback for doing something with the completely rendered
            output.
            Is called: `return callback_finish()` and must return the
            rendered output.
    """

    def __init__(
        self, initialize=None, paint_module=None, paint_text=None, finish=None
    ):
        self._callbacks = {
            "initialize": initialize,
            "paint_module": paint_module,
            "paint_text": paint_text,
            "finish": finish,
        }
        self.module_width = 10
        self.module_height = 10
        self.font_path = os.path.join(PATH, "fonts", "DejaVuSansMono.ttf")
        self.font_size = 10
        self.quiet_zone = 6.5
        self.background = "white"
        self.foreground = "black"
        self.text = ""
        self.human = ""  # human readable text
        self.text_distance = 5
        self.text_line_distance = 1
        self.center_text = True
        self.guard_height_factor = 1.1

    def calculate_size(self, modules_per_line, number_of_lines):
        """Calculates the size of the barcode in pixel.

        :parameters:
            modules_per_line : Integer
                Number of modules in one line.
            number_of_lines : Integer
                Number of lines of the barcode.

        :returns: Width and height of the barcode in pixel.
        :rtype: Tuple
        """
        width = 2 * self.quiet_zone + modules_per_line * self.module_width
        height = 2.0 + self.module_height * number_of_lines
        number_of_text_lines = len(self.text.splitlines())
        if self.font_size and self.text:
            height += (
                pt2mm(self.font_size) / 2 * number_of_text_lines + self.text_distance
            )
            height += self.text_line_distance * (number_of_text_lines - 1)
        return width, height

    def save(self, filename, output):
        """Saves the rendered output to `filename`.

        :parameters:
            filename : String
                Filename without extension.
            output : String
                The rendered output.

        :returns: The full filename with extension.
        :rtype: String
        """
        raise NotImplementedError

    def register_callback(self, action, callback):
        """Register one of the three callbacks if not given at instance
        creation.

        :parameters:
            action : String
                One of 'initialize', 'paint_module', 'paint_text', 'finish'.
            callback : Function
                The callback function for the given action.
        """
        self._callbacks[action] = callback

    def set_options(self, options):
        """Sets the given options as instance attributes (only
        if they are known).

        :parameters:
            options : Dict
                All known instance attributes and more if the childclass
                has defined them before this call.

        :rtype: None
        """
        for key, val in options.items():
            key = key.lstrip("_")
            if hasattr(self, key):
                setattr(self, key, val)

    def packed(self, line):
        """
        Pack line to list give better gfx result, otherwise in can
        result in aliasing gaps
        '11010111' -> [2, -1, 1, -1, 3]

        This method will yield a sequence of pairs (width, height_factor).

        :parameters:
            line: String
                A string matching the writer spec
                (only contain 0 or 1 or G).
        """
        line += " "
        c = 1
        for i in range(0, len(line) - 1):
            if line[i] == line[i + 1]:
                c += 1
            else:
                if line[i] == "1":
                    yield (c, 1)
                elif line[i] == "G":
                    yield (c, self.guard_height_factor)
                else:
                    yield (-c, self.guard_height_factor)
                c = 1

    def render(self, code):
        """Renders the barcode to whatever the inheriting writer provides,
        using the registered callbacks.

        :parameters:
            code : List
                List of strings matching the writer spec
                (only contain 0 or 1 or G).
        """
        if self._callbacks["initialize"] is not None:
            self._callbacks["initialize"](code)
        ypos = 1.0
        base_height = self.module_height
        for cc, line in enumerate(code):
            # Left quiet zone is x startposition
            xpos = self.quiet_zone
            bxs = xpos  # x start of barcode
            text = {
                "start": [],  # The x start of a guard
                "end": [],  # The x end of a guard
                "xpos": [],  # The x position where to write a text block
                # Flag that indicates if the previous mod was part of an guard block:
                "was_guard": False,
            }
            for mod, height_factor in self.packed(line):
                if mod < 1:
                    color = self.background
                else:
                    color = self.foreground

                    if text["was_guard"] and height_factor == 1:
                        # The current guard ended, store its x position
                        text["end"].append(xpos)
                        text["was_guard"] = False
                    elif not text["was_guard"] and height_factor != 1:
                        # A guard started, store its x position
                        text["start"].append(xpos)
                        text["was_guard"] = True

                self.module_height = base_height * height_factor
                # remove painting for background colored tiles?
                self._callbacks["paint_module"](
                    xpos, ypos, self.module_width * abs(mod), color
                )
                xpos += self.module_width * abs(mod)
            else:
                if height_factor != 1:
                    text["end"].append(xpos)
                self.module_height = base_height

            bxe = xpos
            # Add right quiet zone to every line, except last line,
            # quiet zone already provided with background,
            # should it be removed completely?
            if (cc + 1) != len(code):
                self._callbacks["paint_module"](
                    xpos, ypos, self.quiet_zone, self.background
                )
            ypos += self.module_height

        if self.text and self._callbacks["paint_text"] is not None:
            if not text["start"]:
                # If we don't have any start value, print the entire ean
                ypos += self.text_distance
                if self.center_text:
                    # better center position for text
                    xpos = bxs + ((bxe - bxs) / 2.0)
                else:
                    xpos = bxs
                self._callbacks["paint_text"](xpos, ypos)
            else:
                # Else, divide the ean into blocks and print each block
                # in the expected position.
                text["xpos"] = [bxs - 4 * self.module_width]

                # Calculates the position of the text by getting the difference
                # between a guard end and the next start
                text["start"].pop(0)
                for (s, e) in zip(text["start"], text["end"]):
                    text["xpos"].append(e + (s - e) / 2)

                # The last text block is always put after the last guard end
                text["xpos"].append(text["end"][-1] + 4 * self.module_width)

                # Split the ean into its blocks
                self.text = self.text.split(" ")

                ypos += pt2mm(self.font_size)

                blocks = self.text
                for (text, xpos) in zip(blocks, text["xpos"]):
                    self.text = text
                    self._callbacks["paint_text"](xpos, ypos)

        return self._callbacks["finish"]()


class SVGWriter(BaseWriter):
    def __init__(self):
        BaseWriter.__init__(
            self, self._init, self._create_module, self._create_text, self._finish
        )
        self.compress = False
        self.with_doctype = True
        self._document = None
        self._root = None
        self._group = None

    def _init(self, code):
        width, height = self.calculate_size(len(code[0]), len(code))
        self._document = create_svg_object(self.with_doctype)
        self._root = self._document.documentElement
        attributes = {
            "width": SIZE.format(width),
            "height": SIZE.format(height),
        }
        _set_attributes(self._root, **attributes)
        if COMMENT:
            self._root.appendChild(self._document.createComment(COMMENT))
        # create group for easier handling in 3rd party software
        # like corel draw, inkscape, ...
        group = self._document.createElement("g")
        attributes = {"id": "barcode_group"}
        _set_attributes(group, **attributes)
        self._group = self._root.appendChild(group)
        background = self._document.createElement("rect")
        attributes = {
            "width": "100%",
            "height": "100%",
            "style": f"fill:{self.background}",
        }
        _set_attributes(background, **attributes)
        self._group.appendChild(background)

    def _create_module(self, xpos, ypos, width, color):
        # Background rect has been provided already, so skipping "spaces"
        if color != self.background:
            element = self._document.createElement("rect")
            attributes = {
                "x": SIZE.format(xpos),
                "y": SIZE.format(ypos),
                "width": SIZE.format(width),
                "height": SIZE.format(self.module_height),
                "style": f"fill:{color};",
            }
            _set_attributes(element, **attributes)
            self._group.appendChild(element)

    def _create_text(self, xpos, ypos):
        # check option to override self.text with self.human (barcode as
        # human readable data, can be used to print own formats)
        if self.human != "":
            barcodetext = self.human
        else:
            barcodetext = self.text
        for subtext in barcodetext.split("\n"):
            element = self._document.createElement("text")
            attributes = {
                "x": SIZE.format(xpos),
                "y": SIZE.format(ypos),
                "style": "fill:{};font-size:{}pt;text-anchor:middle;".format(
                    self.foreground,
                    self.font_size,
                ),
            }
            _set_attributes(element, **attributes)
            text_element = self._document.createTextNode(subtext)
            element.appendChild(text_element)
            self._group.appendChild(element)
            ypos += pt2mm(self.font_size) + self.text_line_distance

    def _finish(self):
        if self.compress:
            return self._document.toxml(encoding="UTF-8")
        else:
            return self._document.toprettyxml(
                indent=4 * " ", newl=os.linesep, encoding="UTF-8"
            )

    def save(self, filename, output):
        if self.compress:
            _filename = f"{filename}.svgz"
            f = gzip.open(_filename, "wb")
            f.write(output)
            f.close()
        else:
            _filename = f"{filename}.svg"
            with open(_filename, "wb") as f:
                f.write(output)
        return _filename

    def write(self, content, fp: BinaryIO):
        """Write `content` into a file-like object.

        Content should be a barcode rendered by this writer.
        """
        fp.write(content)


if Image is None:
    ImageWriter = None
else:

    class ImageWriter(BaseWriter):  # type: ignore
        format: str
        mode: str
        dpi: int

        def __init__(self, format="PNG", mode="RGB"):
            """Initialise a new write instance.

            :params format: The file format for the generated image. This parameter can
                take any value that Pillow accepts.
            :params mode: The colour-mode for the generated image. Set this to RGBA if
                you wish to use colours with transparency.
            """
            BaseWriter.__init__(
                self, self._init, self._paint_module, self._paint_text, self._finish
            )
            self.format = format
            self.mode = mode
            self.dpi = 300
            self._image = None
            self._draw = None

        def _init(self, code):
            width, height = self.calculate_size(len(code[0]), len(code))
            size = (int(mm2px(width, self.dpi)), int(mm2px(height, self.dpi)))
            self._image = Image.new(self.mode, size, self.background)
            self._draw = ImageDraw.Draw(self._image)

        def _paint_module(self, xpos, ypos, width, color):
            size = [
                (mm2px(xpos, self.dpi), mm2px(ypos, self.dpi)),
                (
                    mm2px(xpos + width, self.dpi),
                    mm2px(ypos + self.module_height, self.dpi),
                ),
            ]
            self._draw.rectangle(size, outline=color, fill=color)

        def _paint_text(self, xpos, ypos):
            font_size = int(mm2px(pt2mm(self.font_size), self.dpi))
            font = ImageFont.truetype(self.font_path, font_size)
            for subtext in self.text.split("\n"):
                width, height = font.getsize(subtext)
                # determine the maximum width of each line
                pos = (
                    mm2px(xpos, self.dpi) - width // 2,
                    mm2px(ypos, self.dpi) - height,
                )
                self._draw.text(pos, subtext, font=font, fill=self.foreground)
                ypos += pt2mm(self.font_size) / 2 + self.text_line_distance

        def _finish(self):
            return self._image

        def save(self, filename, output):
            filename = f"{filename}.{self.format.lower()}"
            output.save(filename, self.format.upper())
            return filename

        def write(self, content, fp: BinaryIO):
            """Write `content` into a file-like object.

            Content should be a barcode rendered by this writer.
            """
            content.save(fp, format=self.format)