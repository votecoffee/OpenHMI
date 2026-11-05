"""PyInstaller entry point; keep multiprocessing bootstrap before application imports."""
import multiprocessing

if __name__ == '__main__':
    multiprocessing.freeze_support()
    from openhmi.launcher import main
    main()
