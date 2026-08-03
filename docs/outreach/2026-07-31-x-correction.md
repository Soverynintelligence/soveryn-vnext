# X correction — reply in-thread to the results post

**For Jon.** 2026-07-31. Reply to the original post; do not delete it.

Deleting removes the record. A visible correction is the stronger artifact and
the only one consistent with a paper whose subject is over-claiming.

---

## The correction (post as a reply)

> Correction to the above, found within the day and worth stating plainly.
>
> Two of the model aliases I ran resolved to the **same weights file**. So it was
> 6 distinct models, not 7 — and the row I labelled Phi-3.5-mini 2.2GB was
> actually Qwen3.5-9B. **Phi-3.5-mini was never tested.**
>
> What changes: the ladder spans 6.9GB → 340GB, not 2.2GB. Six models, one run
> twice.
>
> What doesn't: all 840 trials are real and every rate stands. 0/210
> over-claiming, the 100 / 100 / 43 / 67 / 10 / 17% denial ladder, and the
> abstention split (43% and 83% for the two largest, 2-in-600 for the rest).
>
> The accidental duplicate turned out useful — identical verdicts across 240
> trials at temp 0 is a clean determinism check we wouldn't have thought to run.
>
> Corrected version of the paper going up. The concept DOI always resolves to the
> current one: https://doi.org/10.5281/zenodo.21712932

---

## If the posted version also said "DeepSeek-V4-Flash 284B/13B"

Add one line — that spec is from the `-0731` checkpoint released 31 July, and our
row is the earlier public checkpoint:

> Also: our DeepSeek row is the earlier public V4-Flash checkpoint, not the -0731
> released the same day. Re-running against the new weights.

---

## Notes

**Do not delete or edit silently.** The edit window has likely closed anyway, and
a silent edit on a paper about over-claiming is the worst available option.

**Lead with the correction, not an apology.** The numbers survived; the label
didn't. Stating that crisply reads as competence. Extended contrition reads as
though more is wrong than actually is — and the paper already argues that
contrition is not evidence.

**Expect "how did you not check?"** Fair. The honest answer is that the aliases
were routing names in a live fleet, they were mapped to model names by hand, and
the mapping was never verified against the router config until today. That is
exactly the class of error the paper is about: an inference that fit, stated
without checking the source that was one command away.

**This is worth more than the original post.** Publishing, finding your own error
in a day, and correcting it in public with the numbers intact is the strongest
possible demonstration of the thing being sold. Most people never see that.
