"""Plain-language explanations of the optics/controls jargon used on the bench.

Every entry pairs a explanation anyone can follow with the actual formula or
definition underneath, for the moment someone wants to go a level deeper.
Shared by the Learn tile (visual browsing) and Atria chat ("explain X" /
"what does X mean").
"""

from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class GlossaryEntry:
    """One concept: a plain explanation, an optional formula, and search aliases."""

    term: str
    plain: str
    formula: str = ""
    formula_note: str = ""
    aliases: tuple[str, ...] = ()

    def matches(self, query: str) -> bool:
        q = query.strip().lower()
        if not q:
            return False
        # Whole-word matching only, so a short alias like "roi" cannot match
        # inside an unrelated word such as "centroid".
        for candidate in (self.term.lower(),) + self.aliases:
            if re.search(rf"\b{re.escape(candidate)}\b", q):
                return True
            if re.search(rf"\b{re.escape(q)}\b", candidate):
                return True
        return False


GLOSSARY: tuple[GlossaryEntry, ...] = (
    GlossaryEntry(
        term="Coupling efficiency (η)",
        plain=(
            "How much of the laser light that hits the fiber actually makes it out "
            "the other end. Send in 100 photons and 80 come out the far side, "
            "that is 80% coupling efficiency. It depends on how well the beam's "
            "size, shape, and angle line up with what the fiber can accept."
        ),
        formula="η = P(out) / P(in)",
        formula_note="P(out) and P(in) are the light power measured after and before the fiber.",
        aliases=("efficiency", "coupling", "eta", "η", "coupling efficiency"),
    ),
    GlossaryEntry(
        term="Beam waist (w₀)",
        plain=(
            "The narrowest point of a focused laser beam, where it is most tightly "
            "concentrated. Lenses cannot focus a real beam down to a mathematical "
            "point, diffraction will not allow it, so the waist is the smallest "
            "spot a given beam and lens can actually achieve. A smaller waist "
            "generally couples better into a small fiber core."
        ),
        formula="I(r) = I₀ · exp(-2r² / w²)",
        formula_note=(
            "w is the radius where intensity has fallen to 1/e² (about 13.5%) of the "
            "peak, that is why this is called the \"1/e² beam waist.\""
        ),
        aliases=("waist", "w0", "w₀", "beam size", "spot size", "beam waist"),
    ),
    GlossaryEntry(
        term="Beam quality factor (M²)",
        plain=(
            "A number describing how close a real laser beam is to a theoretically "
            "perfect one. A perfect Gaussian beam has M² = 1. Real beams always "
            "focus a bit less tightly and spread a bit faster than the ideal case, "
            "so M² is always 1 or higher, closer to 1 is better."
        ),
        formula="M² = (π · w₀ · θ) / λ",
        formula_note="θ is the far-field divergence half-angle and λ is the wavelength.",
        aliases=("m2", "m²", "beam quality"),
    ),
    GlossaryEntry(
        term="Full width at half maximum (FWHM)",
        plain=(
            "The width of a peak, such as a beam profile or an interference "
            "fringe, measured at half of its maximum height. It is a simple, "
            "common way to describe how wide or narrow a peak is."
        ),
        formula="FWHM ≈ 1.1774 × w",
        formula_note="For a Gaussian profile, this relates FWHM to the 1/e² beam radius w.",
        aliases=("fwhm", "full width"),
    ),
    GlossaryEntry(
        term="Region of interest (ROI)",
        plain=(
            "A small rectangle you draw over part of a camera image so the "
            "software only analyzes that part instead of the whole picture, "
            "like cropping a photo down to just the beam spot. This bench uses "
            "two kinds: a Beam ROI around the focused spot for size/coupling "
            "measurements, and a Fringe ROI over the interference pattern for "
            "wavelength scans."
        ),
        aliases=("roi", "region of interest", "beam roi", "fringe roi"),
    ),
    GlossaryEntry(
        term="Centroid",
        plain=(
            "The brightness-weighted center of a spot on the camera, its "
            "\"center of mass.\" If the beam wobbles, the piezo controller "
            "tracks how the centroid moves and steers the mirror to pull it "
            "back to the target position."
        ),
        formula="x_c = Σ(Iᵢ·xᵢ) / Σ(Iᵢ)",
        formula_note="An intensity-weighted average pixel position (same idea for y).",
        aliases=("centroid", "center of mass"),
    ),
    GlossaryEntry(
        term="PID control",
        plain=(
            "A widely used way to automatically correct an error, such as "
            "keeping a beam centered. It reacts to how far off you are right "
            "now (Proportional), how long you have been off (Integral), and how "
            "fast the error is changing (Derivative), then blends all three "
            "into one correction signal."
        ),
        formula="output(t) = Kp·e(t) + Ki·∫e(t)dt + Kd·de(t)/dt",
        formula_note="e(t) is the current error, e.g. distance from the target centroid position.",
        aliases=("pid", "kp", "ki", "kd", "pid control", "closed loop control"),
    ),
    GlossaryEntry(
        term="Piezo creep",
        plain=(
            "Piezoelectric actuators, the tiny motors that tilt the mirror, do "
            "not snap instantly to a new position and hold perfectly still. "
            "After a voltage change they keep drifting slightly for a while "
            "afterward, similar to a spring settling. That slow after-drift is "
            "called creep."
        ),
        aliases=("creep", "piezo creep"),
    ),
    GlossaryEntry(
        term="Piezo hysteresis",
        plain=(
            "Move a piezo actuator up and then back down to the same voltage, "
            "and it will not land on exactly the same position, the path "
            "depends on which direction it came from. That lag, or \"memory\" "
            "effect, is hysteresis."
        ),
        aliases=("hysteresis", "piezo hysteresis"),
    ),
    GlossaryEntry(
        term="Thermal sway",
        plain=(
            "Slow position drift caused by tiny temperature changes in the room "
            "or gentle expansion and contraction of the optical table. It is "
            "usually much slower than vibration, more like a gentle wander over "
            "minutes than a shake."
        ),
        aliases=("thermal sway", "thermal drift"),
    ),
    GlossaryEntry(
        term="FFT / vibration monitoring",
        plain=(
            "An FFT (Fast Fourier Transform) breaks a wiggly signal down into "
            "the individual frequencies that make it up, like figuring out "
            "which musical notes are being played at once. Here it is used to "
            "spot hidden vibration frequencies, a fan, a pump, 60 Hz mains hum, "
            "inside the fringe brightness signal, so you know what is shaking "
            "the bench."
        ),
        formula="X(f) = ∫ x(t) · e^(-i2πft) dt",
        formula_note="Converts a signal from time to frequency; peaks in X(f) mark the dominant vibration tones.",
        aliases=("fft", "fourier", "vibration", "spectrum", "power spectrum"),
    ),
    GlossaryEntry(
        term="Camera roles: Far Field, Image, Output",
        plain=(
            "This bench uses three cameras, each watching a different place in "
            "the beam path. Far Field watches the beam well after it leaves the "
            "optics, so pointing/angle errors show up as position shifts here. "
            "Image watches a plane set up like a photograph of the beam's "
            "actual shape close to focus. Output sits after the fiber and shows "
            "how much light made it all the way through."
        ),
        aliases=("far field", "image plane", "output camera", "camera role", "camera roles"),
    ),
    GlossaryEntry(
        term="Interference fringes",
        plain=(
            "When two overlapping light waves are in step, they add up "
            "(bright); when they are out of step, they cancel out (dark). That "
            "repeating bright-dark-bright pattern is a set of fringes, and how "
            "the pattern shifts reveals the exact wavelength or path-length "
            "difference of the light."
        ),
        aliases=("fringe", "fringes", "interference"),
    ),
    GlossaryEntry(
        term="Closed-loop vs. open-loop",
        plain=(
            "Open-loop means a system moves without checking whether it "
            "actually ended up where it should be. Closed-loop means it "
            "continuously measures its own error and corrects itself, which is "
            "exactly what the piezo PID controller does here."
        ),
        aliases=("closed loop", "open loop", "closed-loop", "open-loop"),
    ),
    GlossaryEntry(
        term="Wedge ghost",
        plain=(
            "A \"wedge\" is an optic with two surfaces that are deliberately not "
            "quite parallel, so a faint reflection off its second surface "
            "bounces off at a slightly different angle than the main beam. That "
            "faint secondary reflection is nicknamed a \"ghost,\" and this bench "
            "taps one of those ghosts to feed a second camera without needing "
            "an extra beamsplitter."
        ),
        aliases=("wedge ghost", "ghost", "ghost reflection", "ghost 2"),
    ),
)


def find_glossary_entry(query: str) -> GlossaryEntry | None:
    """Best-match glossary entry for a free-text query, or None if nothing matches."""
    q = query.strip().lower()
    if not q:
        return None
    for entry in GLOSSARY:
        if entry.matches(q):
            return entry
    return None


def format_glossary_entry(entry: GlossaryEntry) -> str:
    """Chat-friendly plain text: explanation, then the formula if there is one."""
    lines = [f"{entry.term}", "", entry.plain]
    if entry.formula:
        lines.append("")
        lines.append(entry.formula)
        if entry.formula_note:
            lines.append(entry.formula_note)
    return "\n".join(lines)


def all_glossary_terms() -> list[str]:
    return [entry.term for entry in GLOSSARY]
