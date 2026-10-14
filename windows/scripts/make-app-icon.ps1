# Builds a Windows .ico from assets/OpenJarvis_Circular_Logo.png.
# The PNG is the only logo checked in; the exe icon format has to be .ico.
param(
    [Parameter(Mandatory = $true)][string]$Png,
    [Parameter(Mandatory = $true)][string]$Ico
)

$ErrorActionPreference = "Stop"
Add-Type -AssemblyName System.Drawing

Add-Type -ReferencedAssemblies System.Drawing -TypeDefinition @"
using System;
using System.Drawing;
using System.Drawing.Drawing2D;
using System.Drawing.Imaging;
using System.IO;
using System.Runtime.InteropServices;

public static class OpenJarvisIco
{
    public static void Write(string pngPath, string icoPath)
    {
        using (var loaded = new Bitmap(pngPath))
        using (var square = Square(loaded))
        {
            int[] sizes = { 16, 24, 32, 48, 64, 128, 256 };
            var images = new Bitmap[sizes.Length];
            try
            {
                for (int i = 0; i < sizes.Length; i++)
                    images[i] = Resize(square, sizes[i]);
                Directory.CreateDirectory(Path.GetDirectoryName(icoPath));
                WriteIco(icoPath, images);
            }
            finally
            {
                for (int i = 0; i < images.Length; i++)
                    if (images[i] != null) images[i].Dispose();
            }
        }
    }

    static Bitmap Square(Bitmap src)
    {
        int side = Math.Max(src.Width, src.Height);
        var dst = new Bitmap(side, side, PixelFormat.Format32bppArgb);
        using (var g = Graphics.FromImage(dst))
        {
            g.Clear(Color.White);
            g.InterpolationMode = InterpolationMode.HighQualityBicubic;
            g.PixelOffsetMode = PixelOffsetMode.HighQuality;
            int x = (side - src.Width) / 2;
            int y = (side - src.Height) / 2;
            g.DrawImage(src, x, y, src.Width, src.Height);
        }
        return dst;
    }

    static Bitmap Resize(Bitmap src, int size)
    {
        var dst = new Bitmap(size, size, PixelFormat.Format32bppArgb);
        using (var g = Graphics.FromImage(dst))
        {
            g.Clear(Color.White);
            g.InterpolationMode = InterpolationMode.HighQualityBicubic;
            g.PixelOffsetMode = PixelOffsetMode.HighQuality;
            g.SmoothingMode = SmoothingMode.HighQuality;
            g.CompositingQuality = CompositingQuality.HighQuality;
            g.DrawImage(src, new Rectangle(0, 0, size, size));
        }
        return dst;
    }

    static void WriteIco(string path, Bitmap[] images)
    {
        var blobs = new byte[images.Length][];
        for (int i = 0; i < images.Length; i++)
            blobs[i] = EncodeBmp(images[i]);

        using (var fs = File.Create(path))
        using (var bw = new BinaryWriter(fs))
        {
            bw.Write((ushort)0);
            bw.Write((ushort)1);
            bw.Write((ushort)images.Length);
            int offset = 6 + (16 * images.Length);
            for (int i = 0; i < images.Length; i++)
            {
                int w = images[i].Width;
                int h = images[i].Height;
                bw.Write((byte)(w >= 256 ? 0 : w));
                bw.Write((byte)(h >= 256 ? 0 : h));
                bw.Write((byte)0);
                bw.Write((byte)0);
                bw.Write((ushort)1);
                bw.Write((ushort)32);
                bw.Write(blobs[i].Length);
                bw.Write(offset);
                offset += blobs[i].Length;
            }
            for (int i = 0; i < blobs.Length; i++)
                bw.Write(blobs[i]);
        }
    }

    static byte[] EncodeBmp(Bitmap bmp)
    {
        int w = bmp.Width;
        int h = bmp.Height;
        int xorSize = w * h * 4;
        int maskStride = ((w + 31) / 32) * 4;
        int maskSize = maskStride * h;
        var rect = new Rectangle(0, 0, w, h);
        var data = bmp.LockBits(rect, ImageLockMode.ReadOnly, PixelFormat.Format32bppArgb);
        try
        {
            int stride = data.Stride;
            byte[] src = new byte[stride * h];
            Marshal.Copy(data.Scan0, src, 0, src.Length);
            using (var ms = new MemoryStream())
            using (var bw = new BinaryWriter(ms))
            {
                bw.Write(40);
                bw.Write(w);
                bw.Write(h * 2);
                bw.Write((ushort)1);
                bw.Write((ushort)32);
                bw.Write(0);
                bw.Write(xorSize + maskSize);
                bw.Write(0);
                bw.Write(0);
                bw.Write(0);
                bw.Write(0);
                for (int y = h - 1; y >= 0; y--)
                {
                    int row = y * stride;
                    for (int x = 0; x < w; x++)
                    {
                        int o = row + x * 4;
                        bw.Write(src[o]);
                        bw.Write(src[o + 1]);
                        bw.Write(src[o + 2]);
                        bw.Write(src[o + 3]);
                    }
                }
                for (int y = 0; y < h; y++)
                {
                    for (int i = 0; i < maskStride; i++)
                        bw.Write((byte)0);
                }
                return ms.ToArray();
            }
        }
        finally
        {
            bmp.UnlockBits(data);
        }
    }
}
"@

[OpenJarvisIco]::Write($Png, $Ico)
