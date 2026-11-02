// Tests for the pure helpers of the timelapse player (frontend/zeitraffer/assets/script.js).
// Run: node --test tests/frontend/player.test.js
const { test } = require("node:test");
const assert = require("node:assert");

const { formatTime, valueText, stepTime } = require("../../frontend/zeitraffer/assets/script.js");

const approx = (actual, expected) => {
	assert.ok(Math.abs(actual - expected) < 1e-9, `${actual} is not ${expected}`);
};

test("formatTime shows minutes and two-digit seconds", () => {
	assert.strictEqual(formatTime(0), "0:00");
	assert.strictEqual(formatTime(7.4), "0:07");
	assert.strictEqual(formatTime(61), "1:01");
	assert.strictEqual(formatTime(3599.9), "59:59");
});

test("formatTime never shows NaN for a video without metadata", () => {
	assert.strictEqual(formatTime(NaN), "0:00");
	assert.strictEqual(formatTime(Infinity), "0:00");
	assert.strictEqual(formatTime(-1), "0:00");
});

test("valueText reads as current of duration in German", () => {
	assert.strictEqual(valueText(7, 12), "0:07 von 0:12");
	assert.strictEqual(valueText(NaN, NaN), "0:00 von 0:00");
});

test("stepTime moves to the middle of the next or previous frame", () => {
	approx(stepTime(0, 1, 10, 12), 0.15);
	approx(stepTime(0.15, 1, 10, 12), 0.25);
	approx(stepTime(0.25, -1, 10, 12), 0.15);
	approx(stepTime(0.3, 1, 20, 12), 0.375);
});

test("stepTime stays inside the video", () => {
	approx(stepTime(0, -1, 10, 12), 0.05);
	approx(stepTime(11.95, 1, 10, 12), 11.95);
});

test("stepTime leaves the position alone for an unusable frame rate", () => {
	assert.strictEqual(stepTime(1.5, 1, 0, 12), 1.5);
	assert.strictEqual(stepTime(1.5, 1, NaN, 12), 1.5);
});
