// Syntra 星樞 真正的桌面主程式執行檔 (Syntra.exe)
using System;
using System.Diagnostics;
using System.IO;
using System.Reflection;
using System.Windows.Forms;

[assembly: AssemblyTitle("Syntra 星樞 桌面協作平台")]
[assembly: AssemblyProduct("Syntra Agent")]
[assembly: AssemblyVersion("2.5.0.0")]

internal static class SyntraApp
{
    [STAThread]
    private static void Main(string[] args)
    {
        string root = AppDomain.CurrentDomain.BaseDirectory.TrimEnd('\\');
        string headless = Path.Combine(root, "syntra_headless.py");

        string custom = Environment.GetEnvironmentVariable("SYNTRA_PYTHON");
        string[] candidates = { string.IsNullOrEmpty(custom) ? null : custom, "python", "py", "python3" };
        string pyExe = null;
        foreach (string c in candidates)
        {
            if (c == null) continue;
            try
            {
                var psiTest = new ProcessStartInfo(c, "-V") { UseShellExecute = false, CreateNoWindow = true };
                using (var p = Process.Start(psiTest))
                {
                    p.WaitForExit();
                    if (p.ExitCode == 0) { pyExe = c; break; }
                }
            }
            catch { }
        }

        if (pyExe == null)
        {
            MessageBox.Show("請先安裝 Python 3.9 以上版本以啟動核心後台。\n官網：https://www.python.org", "Syntra 啟動提示", MessageBoxButtons.OK, MessageBoxIcon.Information);
            return;
        }

        var psi = new ProcessStartInfo(pyExe, "\"" + headless + "\"")
        {
            UseShellExecute = false,
            CreateNoWindow = true,
            WorkingDirectory = root
        };
        psi.EnvironmentVariables["PYTHONIOENCODING"] = "utf-8";
        psi.EnvironmentVariables["PYTHONUTF8"] = "1";

        try
        {
            Process.Start(psi);
        }
        catch (Exception ex)
        {
            MessageBox.Show("無法啟動核心進程: " + ex.Message, "錯誤", MessageBoxButtons.OK, MessageBoxIcon.Error);
        }
    }
}
