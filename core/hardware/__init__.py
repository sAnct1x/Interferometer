"""Hardware abstraction layer.

Every physical device (piezo amplifier chain, cameras) sits behind an interface
so the GUI and control loop never import a concrete driver directly. Today only
the simulated drivers are functional; real serial/Thorcam drivers are stubs that
implement the same interface for when hardware arrives.
"""
