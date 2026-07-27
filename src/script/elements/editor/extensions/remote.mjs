import { Extension } from "@tiptap/core";
import { Plugin, PluginKey } from "@tiptap/pm/state";
import { Decoration, DecorationSet } from "@tiptap/pm/view";

const FLASH_FADE_DURATION_MS = 1000;

export const FlashRemoteChanges = Extension.create({
	name: "flashRemoteChanges",

	addStorage() {
		return {
			color: "",
		};
	},

	addProseMirrorPlugins() {
		const editor = this.editor;
		const storage = this.storage;

		return [
			new Plugin({
				key: new PluginKey("flashRemoteChanges"),

				state: {
					init() {
						return DecorationSet.empty;
					},

					apply(tr, decorations, oldState, newState) {
						const yjsMeta = tr.getMeta("y-sync$");

						const removeDecorationId = tr.getMeta("removeDecoration");
						if (removeDecorationId) {
							const filtered = decorations
								.find()
								.filter(
									(spec) =>
										spec.type.attrs["data-decoration-id"] !==
										removeDecorationId,
								);
							return DecorationSet.create(newState.doc, filtered);
						}

						if (!yjsMeta) {
							return decorations.map(tr.mapping, tr.doc);
						}
						const userColor = storage.color;
						if (!userColor) {
							return decorations.map(tr.mapping, tr.doc);
						}

						const newDecorations = [];

						/**
						 * @testable false
						 * @reason text-position mapping is private remote-flash extension plumbing
						 */
						const buildTextPosMap = (doc) => {
							const map = [];
							let currentTextPos = 0;

							doc.descendants((node, pos) => {
								if (node.isText) {
									for (let i = 0; i < node.text.length; i++) {
										map[currentTextPos++] = pos + i;
									}
								} else if (node.isBlock && currentTextPos > 0) {
									// Account for newline in textBetween for block boundaries
									map[currentTextPos++] = pos;
								}
							});

							return map;
						};

						let docBeforeStep = oldState.doc;
						let prevText = docBeforeStep.textBetween(
							0,
							docBeforeStep.content.size,
							"\n",
							"\n",
						);

						for (let i = 0; i < tr.steps.length; i++) {
							const step = tr.steps[i];
							const map = tr.mapping.maps[i];
							const applyResult = step?.apply?.(docBeforeStep);
							const docAfterStep = applyResult?.doc || docBeforeStep;

							if (!map) {
								docBeforeStep = docAfterStep;
								continue;
							}

							const newText = docAfterStep.textBetween(
								0,
								docAfterStep.content.size,
								"\n",
								"\n",
							);

							if (prevText === newText) {
								docBeforeStep = docAfterStep;
								continue;
							}

							// Find diff region via prefix/suffix matching
							let prefix = 0;
							const minLen = Math.min(prevText.length, newText.length);
							while (
								prefix < minLen &&
								prevText.charCodeAt(prefix) === newText.charCodeAt(prefix)
							) {
								prefix++;
							}

							let suffix = 0;
							const maxSuffix = Math.min(
								prevText.length - prefix,
								newText.length - prefix,
							);
							while (
								suffix < maxSuffix &&
								prevText.charCodeAt(prevText.length - 1 - suffix) ===
									newText.charCodeAt(newText.length - 1 - suffix)
							) {
								suffix++;
							}

							const changeStartText = prefix;
							const changeEndText = newText.length - suffix;

							if (changeEndText > changeStartText) {
								// Map positions through remaining steps to get final positions
								const afterMap = tr.mapping.slice(i + 1);

								// Use the step's intermediate doc to find positions, then map forward
								const stepTextPosMap = buildTextPosMap(docAfterStep);
								const changeStart = stepTextPosMap[changeStartText] || 0;
								const changeEnd =
									stepTextPosMap[changeEndText - 1] + 1 ||
									docAfterStep.content.size;

								const highlightFrom = afterMap.map(changeStart, 1);
								const highlightTo = afterMap.map(changeEnd, -1);

								if (highlightTo > highlightFrom) {
									const decorationId = `flash-${Date.now()}-${Math.random()}`;

									newState.doc.nodesBetween(
										highlightFrom,
										highlightTo,
										(node, pos) => {
											if (!node.isText) return true;
											const start = Math.max(highlightFrom, pos);
											const end = Math.min(highlightTo, pos + node.nodeSize);
											if (end > start) {
												newDecorations.push(
													Decoration.inline(start, end, {
														style: `color: ${userColor};`,
														class: "remote-change-flash",
														"data-decoration-id": decorationId,
													}),
												);
											}
											return true;
										},
									);

									setTimeout(() => {
										if (editor.view) {
											editor.view.dispatch(
												editor.view.state.tr.setMeta(
													"removeDecoration",
													decorationId,
												),
											);
										}
									}, FLASH_FADE_DURATION_MS + 50);
								}
							}

							// Cache text for next iteration
							prevText = newText;
							docBeforeStep = docAfterStep;
						}

						if (newDecorations.length > 0) {
							return decorations.add(newState.doc, newDecorations);
						}
						return decorations.map(tr.mapping, tr.doc);
					},
				},

				props: {
					decorations(state) {
						return this.getState(state);
					},
				},
			}),
		];
	},
});
