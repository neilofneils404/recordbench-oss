"""Bounded pointer positioning must recover displacement without hiding blockers."""
import importlib.util
from pathlib import Path

import pytest
from selenium.common.exceptions import (
    StaleElementReferenceException, TimeoutException, WebDriverException,
)


@pytest.fixture
def journey(monkeypatch):
    scripts = Path(__file__).resolve().parents[1] / 'scripts'
    monkeypatch.syspath_prepend(str(scripts))
    spec = importlib.util.spec_from_file_location('knowledge_journey', scripts / 'browser-accept-matter-knowledge.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class BoundedWait:
    def until(self, predicate):
        for _ in range(12):
            if predicate(self.driver):
                return True
        raise TimeoutException('Synthetic bounded wait exhausted')


class Browser:
    def __init__(self, mode='stable'):
        self.mode = mode
        self.samples = 0
        self.scrolls = 0
        self.clicks = 0
        self.displaced = False
        self.ready_samples = 0
        self.wait = BoundedWait()
        self.wait.driver = self

    def execute_script(self, script, *args):
        if 'scrollIntoView' in script:
            self.scrolls += 1
            self.displaced = False
            return
        if 'document.readyState' in script:
            self.ready_samples += 1
            return 'loading' if self.ready_samples == 1 else 'complete'
        assert 'getBoundingClientRect' in script
        self.samples += 1
        if self.mode == 'displaced' and self.samples == 2:
            self.displaced = True
        top = -200 if self.displaced else 200
        if self.mode == 'moving':
            top += min(self.samples, 3)
        if self.mode == 'never-stable':
            top += self.samples % 2
        hit = self.mode != 'obstructed' and not self.displaced
        box = [10, top, 150, 20]
        # Support the original helper while proving its displacement failure.
        if 'viewport' not in script:
            return box if hit else None
        return dict(box=box, viewport=[1440, 1100], offscreen=self.displaced,
                    unobstructed=hit, hit_tag='A' if hit else 'DIV')

    def click(self):
        self.clicks += 1
        if self.mode == 'click-error':
            raise WebDriverException('Synthetic native click failed')

    def is_enabled(self):
        if self.mode == 'old-document':
            return True
        raise StaleElementReferenceException()


def test_late_scroll_displacement_is_repositioned_before_one_native_click(journey):
    browser = Browser('displaced')
    journey.click_navigation(browser, browser.wait, browser)
    assert browser.scrolls == 1
    assert browser.samples == 4  # visible, displaced, visible, stable visible
    assert browser.clicks == 1
    assert browser.ready_samples == 2


def test_onscreen_obstruction_still_times_out_without_scroll_or_click(journey):
    browser = Browser('obstructed')
    with pytest.raises(TimeoutException):
        journey.click_navigation(browser, browser.wait, browser)
    assert browser.scrolls == 0
    assert browser.clicks == 0


def test_moving_geometry_requires_two_identical_unobstructed_samples(journey):
    browser = Browser('moving')
    journey.click_navigation(browser, browser.wait, browser)
    assert browser.samples == 4
    assert browser.scrolls == 0
    assert browser.clicks == 1
    assert browser.ready_samples == 2


def test_persistent_motion_fails_with_bounded_geometry_telemetry(journey):
    browser = Browser('never-stable')
    with pytest.raises(TimeoutException, match='pointer positioning') as error:
        journey.click_navigation(browser, browser.wait, browser)
    assert 1 <= error.value.msg.count('"box"') <= 6
    assert 'viewport' in error.value.msg and 'hit_tag' in error.value.msg
    assert browser.clicks == 0


@pytest.mark.parametrize('mode', ['click-error', 'old-document'])
def test_click_and_navigation_failures_are_not_retried(journey, mode):
    browser = Browser(mode)
    with pytest.raises(WebDriverException):
        journey.click_navigation(browser, browser.wait, browser)
    assert browser.clicks == 1
