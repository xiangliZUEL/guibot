# Copyright 2013 Intranet AG / Thomas Jarosch and Plamen Dimitrov
#
# guibender is free software: you can redistribute it and/or modify
# it under the terms of the GNU Lesser General Public License as published by
# the Free Software Foundation, either version 3 of the License, or
# (at your option) any later version.
#
# guibender is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
# GNU Lesser General Public License for more details.
#
# You should have received a copy of the GNU Lesser General Public License
# along with guibender.  If not, see <http://www.gnu.org/licenses/>.
#
import time
import os

# interconnected classes - carefully avoid circular reference
from settings import GlobalSettings
from location import Location
from imagelogger import ImageLogger
from errors import *
from image import *
from imagefinder import *
from desktopcontrol import *

import logging
log = logging.getLogger('guibender.region')


class Region(object):
    """
    Region of the screen supporting vertex and nearby region selection,
    validation of expected images, and mouse and keyboard control.
    """

    def __init__(self, xpos=0, ypos=0, width=0, height=0,
                 dc=None, cv=None):
        """
        Build a region object from upleft to downright vertex coordinates.

        :param int xpos: x coordinate of the upleft vertex of the region
        :param int ypos: y coordinate of the upleft vertex of the region
        :param int width: width of the region (xpos+width for downright vertex x)
        :param int height: height of the region (ypos+height for downright vertex y)
        :param dc: DC backend used for any desktop control
        :type dc: :py:class:`desktopcontrol.DesktopControl` or None
        :param cv: CV backend used for any image finding
        :type cv: :py:class:`imagefinder.ImageFinder` or None
        :raises: :py:class:`UninitializedBackendError` if the region is empty

        If any of the backends is not defined a new one will be initiated
        using the parameters defined in :py:class:`settings.GlobalSettings`.
        If `width` or `height` remains zero, it will be set to the maximum
        available within the screen space.
        """
        if dc is None:
            if GlobalSettings.desktop_control_backend == "autopy":
                dc = AutoPyDesktopControl()
            elif GlobalSettings.desktop_control_backend == "qemu":
                dc = QemuDesktopControl()
            elif GlobalSettings.desktop_control_backend == "vncdotool":
                dc = VNCDoToolDesktopControl()
        if cv is None:
            if GlobalSettings.find_image_backend == "autopy":
                cv = AutoPyMatcher()
            elif GlobalSettings.find_image_backend == "contour":
                cv = ContourMatcher()
            elif GlobalSettings.find_image_backend == "template":
                cv = TemplateMatcher()
            elif GlobalSettings.find_image_backend == "feature":
                cv = FeatureMatcher()
            elif GlobalSettings.find_image_backend == "cascade":
                cv = CascadeMatcher()
            elif GlobalSettings.find_image_backend == "text":
                cv = TextMatcher()
            elif GlobalSettings.find_image_backend == "hybrid":
                cv = HybridMatcher()
            elif GlobalSettings.find_image_backend == "deep":
                cv = DeepMatcher()

        # since the backends are read/write make them public attributes
        self.dc_backend = dc
        self.cv_backend = cv
        self.default_target_type = Image

        self._last_match = None
        self._xpos = xpos
        self._ypos = ypos

        # zero width/height implies the one of the available screen
        if width == 0 and self.dc_backend.width != 0:
            self._width = self.dc_backend.width
        else:
            self._width = width
        if height == 0 and self.dc_backend.height != 0:
            self._height = self.dc_backend.height
        else:
            self._height = height
        # clipping should only be performed on initialized screen
        if self.dc_backend.width != 0 and self.dc_backend.height != 0:
            self._ensure_screen_clipping()

        mouse_map = self.dc_backend.mousemap
        for mouse_button in dir(mouse_map):
            if mouse_button.endswith('_BUTTON'):
                setattr(self, mouse_button, getattr(mouse_map, mouse_button))

        key_map = self.dc_backend.keymap
        for key in dir(key_map):
            if not key.startswith('__') and key != "to_string":
                setattr(self, key, getattr(key_map, key))

        mod_map = self.dc_backend.modmap
        for modifier_key in dir(mod_map):
            if modifier_key.startswith('MOD_'):
                setattr(self, modifier_key, getattr(mod_map, modifier_key))

    def _ensure_screen_clipping(self):
        screen_width = self.dc_backend.width
        screen_height = self.dc_backend.height

        if self._xpos < 0:
            self._xpos = 0

        if self._ypos < 0:
            self._ypos = 0

        if self._xpos > screen_width:
            self._xpos = screen_width - 1

        if self._ypos > screen_height:
            self._ypos = screen_height - 1

        if self._xpos + self._width > screen_width:
            self._width = screen_width - self._xpos

        if self._ypos + self._height > screen_height:
            self._height = screen_height - self._ypos

    def get_x(self):
        """
        Getter for readonly attribute.

        :returns: x coordinate of the upleft vertex of the region
        :rtype: int
        """
        return self._xpos
    x = property(fget=get_x)

    def get_y(self):
        """
        Getter for readonly attribute.

        :returns: y coordinate of the upleft vertex of the region
        :rtype: int
        """
        return self._ypos
    y = property(fget=get_y)

    def get_width(self):
        """
        Getter for readonly attribute.

        :returns: width of the region (xpos+width for downright vertex x)
        :rtype: int
        """
        return self._width
    width = property(fget=get_width)

    def get_height(self):
        """
        Getter for readonly attribute.

        :returns: height of the region (ypos+height for downright vertex y)
        :rtype: int
        """
        return self._height
    height = property(fget=get_height)

    def get_center(self):
        """
        Getter for readonly attribute.

        :returns: center of the region
        :rtype: :py:class:`location.Location`
        """
        xpos = self._xpos + self._width / 2
        ypos = self._ypos + self._height / 2

        return Location(xpos, ypos)
    center = property(fget=get_center)

    def get_top_left(self):
        """
        Getter for readonly attribute.

        :returns: upleft vertex of the region
        :rtype: :py:class:`location.Location`
        """
        return Location(self._xpos, self._ypos)
    top_left = property(fget=get_top_left)

    def get_top_right(self):
        """
        Getter for readonly attribute.

        :returns: upright vertex of the region
        :rtype: :py:class:`location.Location`
        """
        return Location(self._xpos + self._width, self._ypos)
    top_right = property(fget=get_top_right)

    def get_bottom_left(self):
        """
        Getter for readonly attribute.

        :returns: downleft vertex of the region
        :rtype: :py:class:`location.Location`
        """
        return Location(self._xpos, self._ypos + self._height)
    bottom_left = property(fget=get_bottom_left)

    def get_bottom_right(self):
        """
        Getter for readonly attribute.

        :returns: downright vertex of the region
        :rtype: :py:class:`location.Location`
        """
        return Location(self._xpos + self._width, self._ypos + self._height)
    bottom_right = property(fget=get_bottom_right)

    def is_empty(self):
        """
        Getter for readonly attribute.

        :returns: whether the region is empty, i.e. has zero size
        :rtype: bool
        """
        return self._width == 0 and self._height == 0
    is_empty = property(fget=is_empty)

    def get_last_match(self):
        """
        Getter for readonly attribute.

        :returns: last match obtained from finding a target within the region
        :rtype: :py:class:`match.Match`
        """
        return self._last_match
    last_match = property(fget=get_last_match)

    def get_mouse_location(self):
        """
        Getter for readonly attribute.

        :returns: mouse location
        :rtype: :py:class:`location.Location`
        """
        return self.dc_backend.get_mouse_location()
    mouse_location = property(fget=get_mouse_location)

    """Main region methods"""
    def nearby(self, rrange=50):
        """
        Obtain a region containing the previous one but enlarged
        by a number of pixels on each side.

        :param int rrange: number of pixels to add
        :returns: new region enlarged by `rrange` on all sides
        :rtype: :py:class:`Region`
        """
        log.debug("Checking nearby the current region")
        new_xpos = self._xpos - rrange
        if new_xpos < 0:
            new_xpos = 0

        new_ypos = self._ypos - rrange
        if new_ypos < 0:
            new_ypos = 0

        new_width = self._width + rrange + self._xpos - new_xpos
        new_height = self._height + rrange + self._ypos - new_ypos

        # Final clipping is done in the Region constructor
        return Region(new_xpos, new_ypos, new_width, new_height,
                      self.dc_backend, self.cv_backend)

    def above(self, rrange=0):
        """
        Obtain a region containing the previous one but enlarged
        by a number of pixels on the upper side.

        :param int rrange: number of pixels to add
        :returns: new region enlarged by `rrange` on upper side
        :rtype: :py:class:`Region`
        """
        log.debug("Checking above the current region")
        if rrange == 0:
            new_ypos = 0
            new_height = self._ypos + self._height
        else:
            new_ypos = self._ypos - rrange
            if new_ypos < 0:
                new_ypos = 0

            new_height = self._height + self._ypos - new_ypos

        # Final clipping is done in the Region constructor
        return Region(self._xpos, new_ypos, self._width, new_height,
                      self.dc_backend, self.cv_backend)

    def below(self, rrange=0):
        """
        Obtain a region containing the previous one but enlarged
        by a number of pixels on the lower side.

        :param int rrange: number of pixels to add
        :returns: new region enlarged by `rrange` on lower side
        :rtype: :py:class:`Region`
        """
        log.debug("Checking below the current region")
        if rrange == 0:
            rrange = self.dc_backend.height

        new_height = self._height + rrange

        # Final clipping is done in the Region constructor
        return Region(self._xpos, self._ypos, self._width, new_height,
                      self.dc_backend, self.cv_backend)

    def left(self, rrange=0):
        """
        Obtain a region containing the previous one but enlarged
        by a number of pixels on the left side.

        :param int rrange: number of pixels to add
        :returns: new region enlarged by `rrange` on left side
        :rtype: :py:class:`Region`
        """
        log.debug("Checking left of the current region")
        if rrange == 0:
            new_xpos = 0
            new_width = self._xpos + self._width
        else:
            new_xpos = self._xpos - rrange
            if new_xpos < 0:
                new_xpos = 0

            new_width = self._width + self._xpos - new_xpos

        # Final clipping is done in the Region constructor
        return Region(new_xpos, self._ypos, new_width, self._height,
                      self.dc_backend, self.cv_backend)

    def right(self, rrange=0):
        """
        Obtain a region containing the previous one but enlarged
        by a number of pixels on the right side.

        :param int rrange: number of pixels to add
        :returns: new region enlarged by `rrange` on right side
        :rtype: :py:class:`Region`
        """
        log.debug("Checking right of the current region")
        if rrange == 0:
            rrange = self.dc_backend.width

        new_width = self._width + rrange

        # Final clipping is done in the Region constructor
        return Region(self._xpos, self._ypos, new_width, self._height,
                      self.dc_backend, self.cv_backend)

    """Image expect methods"""
    def find(self, target, timeout=10):
        """
        Find a target (image, text, etc.) on the screen.

        :param target: target to look for
        :type target: str or :py:class:`image.Target`
        :param int timeout: timeout before giving up
        :returns: match obtained from finding the target within the region
        :rtype: :py:class:`match.Match`
        :raises: :py:class:`errors.FindError` if no match is found

        This method is the main entrance to all our target finding capabilities
        and is the milestone for all target expect methods.
        """
        # handle some specific target types
        if isinstance(target, basestring):
            target = self.default_target_type(target)
        log.debug("Looking for target %s", target)

        if target.use_own_settings:
            log.debug("Using special settings to match %s", target)
            cv_backend = target.match_settings
        else:
            if isinstance(target, Text) and not isinstance(self.cv_backend, TextMatcher):
                raise IncompatibleTargetError("Need text matcher for matching text")
            if isinstance(target, Pattern) and not (isinstance(self.cv_backend, CascadeMatcher) or
                                                   isinstance(self.cv_backend, DeepMatcher)):
                raise IncompatibleTargetError("Need pattern matcher for matching patterns")
            target.match_settings = self.cv_backend
            cv_backend = self.cv_backend
        dc_backend = self.dc_backend

        timeout_limit = time.time() + timeout
        while True:
            screen_capture = dc_backend.capture_screen(self)

            found_pics = cv_backend.find(target, screen_capture)
            if len(found_pics) > 0:
                from match import Match
                match = found_pics[0]
                self._last_match = Match(match.x+self.x, match.y+self.y,
                                         match.width, match.height, match.dx, match.dy,
                                         match.similarity, dc=dc_backend, cv=cv_backend)
                return self._last_match

            elif time.time() > timeout_limit:
                if GlobalSettings.save_needle_on_error:
                    if not os.path.exists(ImageLogger.logging_destination):
                        os.mkdir(ImageLogger.logging_destination)
                    dump_path = GlobalSettings.image_logging_destination
                    hdump_path = os.path.join(dump_path, "last_finderror_haystack.png")
                    ndump_path = os.path.join(dump_path, "last_finderror_needle.png")
                    screen_capture.save(hdump_path)
                    target.save(ndump_path)
                raise FindError(target)

            else:
                # don't hog the CPU
                time.sleep(GlobalSettings.rescan_speed_on_find)

    def find_all(self, target, timeout=10, allow_zero=False):
        """
        Find multiples of a target on the screen.

        :param target: target to look for
        :type target: str or :py:class:`image.Target`
        :param int timeout: timeout before giving up
        :param bool allow_zero: whether to allow zero matches or raise error
        :returns: matches obtained from finding the target within the region
        :rtype: [:py:class:`match.Match`]
        :raises: :py:class:`errors.FindError` if no matches are found
                 and zero matches are not allowed

        This method is similar the one above but allows for more than one match.
        """
        # handle some specific target types
        if isinstance(target, basestring):
            target = self.default_target_type(target)
        log.debug("Looking for multiple occurrences of target %s", target)

        if target.use_own_settings:
            log.debug("Using special settings to match %s", target)
            cv_backend = target.match_settings
        else:
            if isinstance(target, Text) and not isinstance(self.cv_backend, TextMatcher):
                raise IncompatibleTargetError("Need text matcher for matching text")
            if isinstance(target, Pattern) and not (isinstance(self.cv_backend, CascadeMatcher) or
                                                   isinstance(self.cv_backend, DeepMatcher)):
                raise IncompatibleTargetError("Need pattern matcher for matching patterns")
            target.match_settings = self.cv_backend
            cv_backend = self.cv_backend
        dc_backend = self.dc_backend

        # TODO: decide about updating the last_match attribute
        last_matches = []
        timeout_limit = time.time() + timeout
        while True:
            screen_capture = dc_backend.capture_screen(self)

            found_pics = cv_backend.find(target, screen_capture)
            if len(found_pics) > 0:
                from match import Match
                for match in found_pics:
                    last_matches.append(Match(match.x+self.x, match.y+self.y,
                                              match.width, match.height, match.dx, match.dy,
                                              match.similarity, dc=dc_backend, cv=cv_backend))
                self._last_match = last_matches[-1]
                return last_matches

            elif time.time() > timeout_limit:
                if allow_zero:
                    return last_matches
                else:
                    if GlobalSettings.save_needle_on_error:
                        log.info("Dumping the haystack at /tmp/guibender_last_finderror.png")
                        screen_capture.save('/tmp/guibender_last_finderror.png')
                        target.save('/tmp/guibender_last_finderror_needle.png')
                    raise FindError(target)

            else:
                # don't hog the CPU
                time.sleep(GlobalSettings.rescan_speed_on_find)

    def sample(self, image):
        """
        Sample the similarity between and image and the screen,
        i.e. an empirical probability that the image is on the screen.

        :param image: image to look for
        :type image: str or :py:class:`image.Image`
        :returns: similarity with best match on the screen
        :rtype: float

        .. note:: Not all matchers support a 'similarity' value. The ones that don't
            will return zero similarity (similarly to the image logging case).
        """
        log.debug("Looking for image %s", image)
        if isinstance(image, basestring):
            image = Image(image)
        if not image.use_own_settings:
            image.match_settings = self.cv_backend
            image.use_own_settings = True
        image = image.with_similarity(0.0)
        match = self.find(image)
        similarity = match.similarity
        return similarity

    def exists(self, target, timeout=0):
        """
        Check if a target exists on the screen using the matching
        success as a threshold for the existence.

        :param target: target to look for
        :type target: str or :py:class:`image.Target`
        :param int timeout: timeout before giving up
        :returns: match obtained from finding the target within the region
                  or nothing if no match is found
        :rtype: :py:class:`match.Match` or None
        """
        log.debug("Checking if %s is present", target)
        try:
            return self.find(target, timeout)
        except FindError:
            pass
        return None

    def wait(self, target, timeout=30):
        """
        Wait for a target to appear (be matched) with a given timeout
        as failing tolerance.

        :param target: target to look for
        :type target: str or :py:class:`image.Target`
        :param int timeout: timeout before giving up
        :returns: match obtained from finding the target within the region
        :rtype: :py:class:`match.Match`
        :raises: :py:class:`errors.FindError` if no match is found
        """
        log.info("Waiting for %s", target)
        return self.find(target, timeout)

    def wait_vanish(self, target, timeout=30):
        """
        Wait for a target to disappear (be unmatched, i.e. matched
        without success) with a given timeout as failing tolerance.

        :param target: target to look for
        :type target: str or :py:class:`image.Target`
        :param int timeout: timeout before giving up
        :returns: whether the target disappeared from the region
        :rtype: bool
        :raises: :py:class:`errors.NotFindError` if match is still found
        """
        log.info("Waiting for %s to vanish", target)
        expires = time.time() + timeout
        while time.time() < expires:
            if self.exists(target, 0) is None:
                return True

            # don't hog the CPU
            time.sleep(0.2)

        # target is still there
        raise NotFindError(target)

    """Mouse methods"""
    def idle(self, timeout):
        """
        Wait for a number of seconds and continue the nested call chain.

        :param int timeout: timeout to wait for
        :returns: self
        :rtype: :py:class:`Region`

        This method can be used as both a way to compactly wait for some time
        while not breaking the call chain. e.g.::

            aregion.hover('abox').idle(1).click('aboxwithinthebox')

        and as a way to conveniently perform timeout in between actions.
        """
        log.debug("Waiting for %ss", timeout)
        time.sleep(timeout)
        return self

    def hover(self, target_or_location):
        """
        Hover the mouse over a target or location.

        :param target_or_location: target or location to hover to
        :type target_or_location: :py:class:`match.Match` or :py:class:`location.Location` or
                                 str or :py:class:`image.Target`
        :returns: match from finding the target or nothing if hovering over a known location
        :rtype: :py:class:`match.Match` or None
        """
        log.info("Hovering over %s", target_or_location)

        # Handle Match
        from match import Match
        if isinstance(target_or_location, Match):
            self.dc_backend.mouse_move(target_or_location.target)
            return None

        # Handle Location
        if isinstance(target_or_location, Location):
            self.dc_backend.mouse_move(target_or_location)
            return None

        # Find target (image, text, pattern) or str
        match = self.find(target_or_location)
        self.dc_backend.mouse_move(match.target)

        return match

    def click(self, target_or_location, modifiers=None):
        """
        Click on a target or location using the left mouse button and
        optionally holding special keys.

        :param target_or_location: target or location to click on
        :type target_or_location: :py:class:`match.Match` or :py:class:`location.Location` or
                                 str or :py:class:`image.Target`
        :param modifiers: special keys to hold during clicking
                         (see :py:class:`inputmap.KeyModifier` for extensive list)
        :type modifiers: [str]
        :returns: match from finding the target or nothing if clicking on a known location
        :rtype: :py:class:`match.Match` or None

        The special keys refer to a list of key modifiers, e.g.::

            self.click('my_target', [KeyModifier.MOD_CTRL, 'x']).
        """
        match = self.hover(target_or_location)
        log.info("Clicking at %s", target_or_location)
        if modifiers != None:
            log.info("Holding the modifiers %s", " ".join(modifiers))
        self.dc_backend.mouse_click(self.LEFT_BUTTON, 1, modifiers)
        return match

    def right_click(self, target_or_location, modifiers=None):
        """
        Click on a target or location using the right mouse button and
        optionally holding special keys.

        Arguments and return values are analogical to :py:func:`Region.click`.
        """
        match = self.hover(target_or_location)
        log.info("Right clicking at %s", target_or_location)
        if modifiers != None:
            log.info("Holding the modifiers %s", " ".join(modifiers))
        self.dc_backend.mouse_click(self.RIGHT_BUTTON, 1, modifiers)
        return match

    def double_click(self, target_or_location, modifiers=None):
        """
        Double click on a target or location using the left mouse button
        and optionally holding special keys.

        Arguments and return values are analogical to :py:func:`Region.click`.
        """
        match = self.hover(target_or_location)
        log.info("Double clicking at %s", target_or_location)
        if modifiers != None:
            log.info("Holding the modifiers %s", " ".join(modifiers))
        self.dc_backend.mouse_click(self.LEFT_BUTTON, 2, modifiers)
        return match

    def multi_click(self, target_or_location, count=3, modifiers=None):
        """
        Click N times on a target or location using the left mouse button
        and optionally holding special keys.

        Arguments and return values are analogical to :py:func:`Region.click`.
        """
        match = self.hover(target_or_location)
        log.info("Clicking %s times at %s", count, target_or_location)
        if modifiers != None:
            log.info("Holding the modifiers %s", " ".join(modifiers))
        self.dc_backend.mouse_click(self.LEFT_BUTTON, count, modifiers)
        return match

    def mouse_down(self, target_or_location, button=None):
        """
        Hold down an arbitrary mouse button on a target or location.

        :param target_or_location: target or location to toggle on
        :type target_or_location: :py:class:`match.Match` or :py:class:`location.Location` or
                                 str or :py:class:`image.Target`
        :param button: button index depending on backend (default is left button)
                       (see :py:class:`inputmap.MouseButton` for extensive list)
        :type button: int or None
        :returns: match from finding the target or nothing if toggling on a known location
        :rtype: :py:class:`match.Match` or None
        """
        if button is None:
            button = self.LEFT_BUTTON
        match = self.hover(target_or_location)
        log.debug("Holding down the mouse at %s", target_or_location)
        self.dc_backend.mouse_down(button)
        return match

    def mouse_up(self, target_or_location, button=None):
        """
        Release an arbitrary mouse button on a target or location.

        :param target_or_location: target or location to toggle on
        :type target_or_location: :py:class:`match.Match` or :py:class:`location.Location` or
                                 str or :py:class:`image.Target`
        :param button: button index depending on backend (default is left button)
                       (see :py:class:`inputmap.MouseButton` for extensive list)
        :type button: int or None
        :returns: match from finding the target or nothing if toggling on a known location
        :rtype: :py:class:`match.Match` or None
        """
        if button is None:
            button = self.LEFT_BUTTON
        match = self.hover(target_or_location)
        log.debug("Holding up the mouse at %s", target_or_location)
        self.dc_backend.mouse_up(button)
        return match

    def drag_drop(self, src_target_or_location, dst_target_or_location, modifiers=None):
        """
        Drag from and drop at a target or location optionally holding special keys.

        :param src_target_or_location: target or location to drag from
        :type src_target_or_location: :py:class:`match.Match` or :py:class:`location.Location` or
                                     str or :py:class:`image.Target`
        :param dst_target_or_location: target or location to drop at
        :type dst_target_or_location: :py:class:`match.Match` or :py:class:`location.Location` or
                                     str or :py:class:`image.Target`
        :param modifiers: special keys to hold during dragging and dropping
                         (see :py:class:`inputmap.KeyModifier` for extensive list)
        :type modifiers: [str]
        :returns: match from finding the target or nothing if dropping at a known location
        :rtype: :py:class:`match.Match` or None
        """
        self.drag_from(src_target_or_location, modifiers)
        match = self.drop_at(dst_target_or_location, modifiers)
        return match

    def drag_from(self, target_or_location, modifiers=None):
        """
        Drag from a target or location optionally holding special keys.

        Arguments and return values are analogical to :py:func:`Region.drag_drop`
        but with `target_or_location` as `src_target_or_location`.
        """
        match = self.hover(target_or_location)

        time.sleep(0.2)
        if modifiers != None:
            log.info("Holding the modifiers %s", " ".join(modifiers))
            self.dc_backend.keys_toggle(modifiers, True)
            #self.dc_backend.keys_toggle(["Ctrl"], True)

        log.info("Dragging %s", target_or_location)
        self.dc_backend.mouse_down(self.LEFT_BUTTON)
        time.sleep(GlobalSettings.delay_after_drag)

        return match

    def drop_at(self, target_or_location, modifiers=None):
        """
        Drop at a target or location optionally holding special keys.

        Arguments and return values are analogical to :py:func:`Region.drag_drop`
        but with `target_or_location` as `dst_target_or_location`.
        """
        match = self.hover(target_or_location)
        time.sleep(GlobalSettings.delay_before_drop)

        log.info("Dropping at %s", target_or_location)
        self.dc_backend.mouse_up(self.LEFT_BUTTON)

        time.sleep(0.5)
        if modifiers != None:
            log.info("Holding the modifiers %s", " ".join(modifiers))
            self.dc_backend.keys_toggle(modifiers, False)

        return match

    """Keyboard methods"""
    def press_keys(self, keys):
        """
        Press a single key or a list of keys simultaneously.

        :param keys: characters or special keys depending on the backend
                     (see :py:class:`inputmap.Key` for extensive list)
        :type keys: [str] or str (possibly special keys in both cases)

        Thus, the line ``self.press_keys([Key.ENTER])`` is equivalent to
        the line ``self.press_keys(Key.ENTER)``. Other examples are::

            self.press_keys([Key.CTRL, 'X'])
            self.press_keys(['a', 'b', 3])
        """
        keys_list = self._parse_keys(keys)
        time.sleep(GlobalSettings.delay_before_keys)
        self.dc_backend.keys_press(keys_list)
        return self

    def press_at(self, keys, target_or_location):
        """
        Press a single key or a list of keys simultaneously
        at a specified target or location.

        This method is similar to :py:func:`Region.press_keys` but
        with an extra argument like :py:func:`Region.click`.
        """
        keys_list = self._parse_keys(keys, target_or_location)
        match = self.click(target_or_location)
        time.sleep(GlobalSettings.delay_before_keys)
        self.dc_backend.keys_press(keys_list)
        return match

    def _parse_keys(self, keys, target_or_location=None):
        at_str = " at %s" % target_or_location if target_or_location else ""

        keys_list = []
        # if not a list (i.e. if a single key)
        if isinstance(keys, int) or isinstance(keys, basestring):
            key = keys
            try:
                log.info("Pressing key '%s'%s", self.dc_backend.keymap.to_string(key), at_str)
            # if not a special key (i.e. if a character key)
            except KeyError:
                if isinstance(key, int):
                    key = str(key)
                elif len(key) > 1:
                    raise # a key cannot be a string (text)
                log.info("Pressing key '%s'%s", key, at_str)
            keys_list.append(key)
        else:
            key_strings = []
            for key in keys:
                try:
                    key_strings.append(self.dc_backend.keymap.to_string(key))
                except KeyError:
                    if isinstance(key, int):
                        key = str(key)
                    elif len(key) > 1:
                        raise # a key cannot be a string (text)
                    key_strings.append(key)
                keys_list.append(key)
            log.info("Pressing together keys '%s'%s",
                     "'+'".join(keystr for keystr in key_strings),
                     at_str)
        return keys_list

    def type_text(self, text, modifiers=None):
        """
        Type a list of consecutive character keys (without special keys).

        :param text: characters or strings (independent of the backend)
        :type text: [str] or str (no special keys in both cases)
        :param modifiers: special keys to hold during typing
                         (see :py:class:`inputmap.KeyModifier` for extensive list)
        :type modifiers: [str]

        Thus, the line ``self.type_text(['hello'])`` is equivalent to
        the line ``self.type_text('hello')``. Other examples are::

            self.type_text('ab3') # compare with press_keys()
            self.type_text(['Hello', ' ', 'user3614']) # in cases with appending

        Special keys are only allowed as modifiers here - simply call
        :py:func:`Region.press_keys` multiple times for consecutively
        typing special keys.
        """
        text_list = self._parse_text(text)
        time.sleep(GlobalSettings.delay_before_keys)
        if modifiers != None:
            if isinstance(modifiers, basestring):
                modifiers = [modifiers]
            log.info("Holding the modifiers '%s'", "'+'".join(modifiers))
        self.dc_backend.keys_type(text_list, modifiers)
        return self

    def type_at(self, text, target_or_location, modifiers=None):
        """
        Type a list of consecutive character keys (without special keys)
        at a specified target or location.

        This method is similar to :py:func:`Region.type_text` but
        with an extra argument like :py:func:`Region.click`.
        """
        text_list = self._parse_text(text, target_or_location)
        match = None
        if target_or_location != None:
            match = self.click(target_or_location)
        time.sleep(GlobalSettings.delay_before_keys)
        if modifiers != None:
            if isinstance(modifiers, basestring):
                modifiers = [modifiers]
            log.info("Holding the modifiers '%s'", "'+'".join(modifiers))
        self.dc_backend.keys_type(text_list, modifiers)
        return match

    def _parse_text(self, text, target_or_location=None):
        at_str = " at %s" % target_or_location if target_or_location else ""

        text_list = []
        if isinstance(text, basestring):
            log.info("Typing text '%s'%s", text, at_str)
            text_list = [text]
        else:
            for part in text:
                if isinstance(part, basestring):
                    log.info("Typing text '%s'%s", part, at_str)
                    text_list.append(part)
                elif isinstance(part, int):
                    log.info("Typing '%i'%s", part, at_str)
                    text_list.append(str(part))
                else:
                    raise ValueError("Unknown text character" % part)
        return text_list
