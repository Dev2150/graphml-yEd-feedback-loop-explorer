from src.ui.desktop.main_window import GraphMLExplorerApp


def run_gui(input_file: str, output_folder: str):
	app = GraphMLExplorerApp(input_file, output_folder)
	try:
		app.mainloop()
	finally:
		app.controller.restore_console_redirect()
