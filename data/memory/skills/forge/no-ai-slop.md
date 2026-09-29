# No AI slop

- id: no-ai-slop
- owner: kernel
- when: writing or editing prose, site copy, chat replies, or when Jon says slop, punchy, em dash
- gated_tools: none

Source: https://github.com/petergyang/no-ai-slop
Full rules: `/home/jon-deoliveira/.grok/skills/no-ai-slop/SKILL.md` and `eval.md`.

Soul.md still wins: few words, no filler, no pep talk.

## Procedure
1. Keep the point and Kernel's voice. Minimum edit. Do not polish into a catalog.
2. Cut banned words: delve, foster, leverage, utilize, facilitate, empower, streamline, robust, cutting-edge, paradigm shift, game changer, tapestry, realm, beacon, multifaceted, meticulous, intricate, paramount, transformative, elevate, embark, supercharge, harness, ever-evolving.
3. Cut patterns: "It's not X, it's Y." Throat-clearing ("Here's the thing"). Faux insight ("What nobody tells you"). Colon drama. "Highlighting/underscoring." Puffery ("pivotal moment," "testament"). Weasel "studies show." Synonym cycling. Dramatic fragments. Fake-profound kickers. "In conclusion."
4. Em dashes: none in short copy. CWG public copy: none, ever. Period, comma, or colon.
5. Concrete names, numbers, towns, files. If a sentence could sit on another company's site unchanged, cut it.
6. Check `eval.md` before you ship.

## Verify
- Sounds like Kernel, not a launch post.
- No binary contrast, no kicker aphorism, no emoji headings.
- CWG: `python3 ~/carolinawatergardens/_check_copy.py` still green.
